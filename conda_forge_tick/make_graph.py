import re
import collections.abc
import hashlib
import logging
import os
import time
from collections import defaultdict
from concurrent.futures import as_completed
from copy import deepcopy
import typing
from requests import Response
from typing import List, Optional, Set

import networkx as nx
import requests
import yaml

from xonsh.lib.collections import ChainDB, _convert_to_dict
from .xonsh_utils import env

from conda_forge_tick.utils import as_iterable
from .all_feedstocks import get_all_feedstocks
from .utils import (
    parse_meta_yaml,
    setup_logger,
    get_requirements,
    executor,
    load_graph,
    dump_graph,
    LazyJson,
)
from .contexts import GithubContext

if typing.TYPE_CHECKING:
    from .cli import CLIArgs
    from .migrators_types import RequirementsTypedDict, TestTypedDict

logger = logging.getLogger("conda_forge_tick.make_graph")
pin_sep_pat = re.compile(r" |>|<|=|\[")


NUM_GITHUB_THREADS = 2

github_username = env.get("USERNAME", "")
github_password = env.get("PASSWORD", "")
github_token = env.get("GITHUB_TOKEN")

ghctx = GithubContext(
    github_username=github_username,
    github_password=github_password,
    github_token=github_token,
    circle_build_url=os.getenv("CIRCLE_BUILD_URL", ""),
)


def _fetch_file(name: str, filepath: str) -> typing.Union[str, Response]:
    r = requests.get(
        "https://raw.githubusercontent.com/"
        "conda-forge/{}-feedstock/master/{}".format(name, filepath),
    )
    if r.status_code != 200:
        logger.error(
            f"Something odd happened when fetching recipe {name}: {r.status_code}",
        )
        return r

    text = r.content.decode("utf-8")
    return text


# TODO: include other files like build_sh
def populate_feedstock_attributes(
    name: str,
    sub_graph: LazyJson,
    meta_yaml: typing.Union[str, Response] = "",
    conda_forge_yaml: typing.Union[str, Response] = "",
    # build_sh: typing.Union[str, Response] = "",
    # pre_unlink: typing.Union[str, Response] = "",
    # post_link: typing.Union[str, Response] = "",
    # pre_link: typing.Union[str, Response] = "",
    # activate: typing.Union[str, Response] = "",
) -> LazyJson:
    """Parse the various configuration information into something usable

    Notes
    -----
    If the return is bad hand the response itself in so that it can be parsed
    for meaning.
    """
    sub_graph.update({"feedstock_name": name, "bad": False})
    # handle all the raw strings
    if isinstance(meta_yaml, Response):
        sub_graph["bad"] = f"make_graph: {meta_yaml.status_code}"
        return sub_graph
    sub_graph["raw_meta_yaml"] = meta_yaml

    # Get the conda-forge.yml
    if isinstance(conda_forge_yaml, str):
        sub_graph["conda-forge.yml"] = {
            k: v
            for k, v in yaml.safe_load(conda_forge_yaml).items()
            if k
            in {
                "provider",
                "min_r_ver",
                "min_py_ver",
                "max_py_ver",
                "max_r_ver",
                "compiler_stack",
                "bot",
            }
        }

    yaml_dict = ChainDB(
        *[parse_meta_yaml(meta_yaml, platform=plat) for plat in ["win", "osx", "linux"]]
    )
    if not yaml_dict:
        logger.error(f"Something odd happened when parsing recipe {name}")
        sub_graph["bad"] = "make_graph: Could not parse"
        return sub_graph
    sub_graph["meta_yaml"] = _convert_to_dict(yaml_dict)
    meta_yaml = sub_graph["meta_yaml"]

    sub_graph["strong_exports"] = False
    # TODO: make certain to remove None
    requirements_dict = defaultdict(set)
    for block in [meta_yaml] + meta_yaml.get("outputs", []) or []:
        req: "RequirementsTypedDict" = block.get("requirements", {}) or {}
        if isinstance(req, list):
            requirements_dict["run"].update(set(req))
            continue
        for section in ["build", "host", "run"]:
            requirements_dict[section].update(
                list(as_iterable(req.get(section, []) or []))
            )
        test: "TestTypedDict" = block.get("test", {})
        requirements_dict["test"].update(test.get("requirements", []) or [])
        requirements_dict["test"].update(test.get("requires", []) or [])
        run_exports = (block.get("build", {}) or {}).get("run_exports", {})
        if isinstance(run_exports, dict) and run_exports.get("strong"):
            sub_graph["strong_exports"] = True
    for k in list(requirements_dict.keys()):
        requirements_dict[k] = set(v for v in requirements_dict[k] if v)

    sub_graph["total_requirements"] = dict(requirements_dict)
    sub_graph["requirements"] = {
        k: {pin_sep_pat.split(x)[0].lower() for x in v}
        for k, v in sub_graph["total_requirements"].items()
    }

    # handle multi outputs
    if "outputs" in yaml_dict:
        sub_graph["outputs_names"] = sorted(
            list({d.get("name", "") for d in yaml_dict["outputs"]}),
        )

    # TODO: Write schema for dict
    # TODO: remove this
    req = get_requirements(yaml_dict)
    sub_graph["req"] = req

    keys = [("package", "name"), ("package", "version")]
    missing_keys = [k[1] for k in keys if k[1] not in yaml_dict.get(k[0], {})]
    source = yaml_dict.get("source", [])
    if isinstance(source, collections.abc.Mapping):
        source = [source]
    source_keys: Set[str] = set()
    for s in source:
        if not sub_graph.get("url"):
            sub_graph["url"] = s.get("url")
        source_keys |= s.keys()
    if "url" not in source_keys:
        missing_keys.append("url")
    if missing_keys:
        logger.error(f"Recipe {name} doesn't have a {', '.join(missing_keys)}")
    for k in keys:
        if k[1] not in missing_keys:
            sub_graph[k[1]] = yaml_dict[k[0]][k[1]]
    kl = list(sorted(source_keys & hashlib.algorithms_available, reverse=True))
    if kl:
        sub_graph["hash_type"] = kl[0]
    return sub_graph


def get_attrs(name: str, i: int) -> LazyJson:
    # These fetches could be done via async/multiprocessing
    meta_yaml = _fetch_file(name, "recipe/meta.yaml")
    conda_forge_yaml = _fetch_file(name, "conda-forge.yml")

    lzj = LazyJson(f"node_attrs/{name}.json")
    with lzj as sub_graph:
        populate_feedstock_attributes(
            name, sub_graph, meta_yaml=meta_yaml, conda_forge_yaml=conda_forge_yaml,
        )
    return lzj


def _build_graph_process_pool(
    gx: nx.DiGraph, names: List[str], new_names: List[str],
) -> None:
    with executor("thread", max_workers=20) as pool:
        futures = {
            pool.submit(get_attrs, name, i): name for i, name in enumerate(names)
        }
        logger.info("submitted all nodes")

        n_tot = len(futures)
        n_left = len(futures)
        start = time.time()
        eta = -1
        for f in as_completed(futures):
            n_left -= 1
            if n_left % 10 == 0:
                eta = (time.time() - start) / (n_tot - n_left) * n_left
            name = futures[f]
            try:
                sub_graph = {"payload": f.result()}
                logger.info("itr % 5d - eta % 5ds: finished %s", n_left, eta, name)
            except Exception as e:
                logger.error(
                    "itr % 5d - eta % 5ds: Error adding %s to the graph: %s",
                    n_left,
                    eta,
                    name,
                    repr(e),
                )
            else:
                if name in new_names:
                    gx.add_node(name, **sub_graph)
                else:
                    gx.nodes[name].update(**sub_graph)


def _build_graph_sequential(
    gx: nx.DiGraph, names: List[str], new_names: List[str],
) -> None:
    for i, name in enumerate(names):
        try:
            sub_graph = {"payload": get_attrs(name, i)}
        except Exception as e:
            logger.error(f"Error adding {name} to the graph: {e}")
        else:
            if name in new_names:
                gx.add_node(name, **sub_graph)
            else:
                gx.nodes[name].update(**sub_graph)


def make_graph(names: List[str], gx: Optional[nx.DiGraph] = None) -> nx.DiGraph:
    logger.info("reading graph")

    if gx is None:
        gx = nx.DiGraph()

    new_names = [name for name in names if name not in gx.nodes]
    old_names = [name for name in names if name in gx.nodes]
    # silly typing force
    assert gx is not None
    old_names = sorted(  # type: ignore
        old_names, key=lambda n: gx.nodes[n].get("time", 0)
    )  # type: ignore

    total_names = new_names + old_names
    logger.info("start feedstock fetch loop")
    from .xonsh_utils import env

    debug = env.get("CONDA_FORGE_TICK_DEBUG", False)
    builder = _build_graph_sequential if debug else _build_graph_process_pool
    builder(gx, total_names, new_names)
    logger.info("feedstock fetch loop completed")

    gx2 = deepcopy(gx)
    logger.info("inferring nodes and edges")

    # make the outputs look up table so we can link properly
    outputs_lut = {
        k: node_name
        for node_name, node in gx.nodes.items()
        for k in node.get("payload", {}).get("outputs_names", [])
    }
    # add this as an attr so we can use later
    gx.graph["outputs_lut"] = outputs_lut
    strong_exports = {
        node_name
        for node_name, node in gx.nodes.items()
        if node.get("payload").get("strong_exports", False)
    }
    # This drops all the edge data and only keeps the node data
    gx = nx.create_empty_copy(gx)
    # TODO: label these edges with the kind of dep they are and their platform
    for node, node_attrs in gx2.nodes.items():
        with node_attrs["payload"] as attrs:
            # replace output package names with feedstock names via LUT
            deps = set(
                map(
                    lambda x: outputs_lut.get(x, x),
                    set().union(*attrs.get("requirements", {}).values()),
                )
            )

            # handle strong run exports
            overlap = deps & strong_exports
            requirements = attrs.get("requirements")
            if requirements:
                requirements["host"].update(overlap)
                requirements["run"].update(overlap)

        for dep in deps:
            if dep not in gx.nodes:
                # for packages which aren't feedstocks and aren't outputs
                # usually these are stubs
                lzj = LazyJson(f"node_attrs/{dep}.json")
                lzj.update(feedstock_name=dep, bad=False, archived=True)
                gx.add_node(dep, payload=lzj)
            gx.add_edge(dep, node)
    logger.info("new nodes and edges infered")
    return gx


def update_nodes_with_bot_rerun(gx):
    """Go through all the open PRs and check if they are rerun"""
    for name, node in gx.nodes.items():
        with node['payload'] as payload:
            for migration in payload.get('PRed', []):
                pr_json = migration.get('PR', {})
                # if there is a valid PR and it isn't currently listed as rerun
                # but the PR needs a rerun
                if (
                    pr_json
                    and not migration['data']['bot_rerun']
                    and "bot-rerun" in [l["name"] for l in pr_json.get("labels", [])]
                ):
                    migration['data']['bot_rerun'] = time.time()
                    logger.INFO(
                        "BOT-RERUN %s: processing bot rerun label for migration %s",
                        node,
                        migration["data"],
                    )


def main(args: "CLIArgs") -> None:
    setup_logger(logger)

    names = get_all_feedstocks(cached=True)
    if os.path.exists("graph.json"):
        gx = load_graph()
    else:
        gx = None
    gx = make_graph(names, gx)
    print(
        "nodes w/o payload:",
        [k for k, v in gx.nodes.items() if "payload" not in v],
    )

    update_nodes_with_bot_rerun(gx)

    dump_graph(gx)


if __name__ == "__main__":
    pass
    # main()
