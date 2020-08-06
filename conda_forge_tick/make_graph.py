import collections.abc
import hashlib
import logging
import os
import re
import tempfile
import glob
import zipfile
import time
import typing
from concurrent.futures import as_completed

# import joblib
from copy import deepcopy
from typing import List, Optional, Set

import json
import networkx as nx
import requests
import yaml
import tqdm
from requests import Response
from xonsh.lib.collections import ChainDB, _convert_to_dict

from conda_forge_tick.utils import extract_requirements
from .all_feedstocks import get_all_feedstocks
from .contexts import GithubContext
from .utils import (
    parse_meta_yaml,
    setup_logger,
    get_requirements,
    executor,
    load_graph,
    dump_graph,
    LazyJson,
)
from .xonsh_utils import env

if typing.TYPE_CHECKING:
    from .cli import CLIArgs

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


def _fetch_static_repo(name, dest):
    r = requests.get(
        f"https://github.com/conda-forge/{name}-feedstock/archive/master.zip",
    )
    if r.status_code != 200:
        logger.error(
            f"Something odd happened when fetching feedstock {name}: {r.status_code}",
        )
        r.raise_for_status()

    zname = os.path.join(dest, f"{name}-feedstock-master.zip")

    with open(zname, "wb") as fp:
        fp.write(r.content)

    z = zipfile.ZipFile(zname)
    z.extractall(path=dest)
    dest_dir = os.path.join(dest, os.path.split(z.namelist()[0])[0])
    return dest_dir


# TODO: include other files like build_sh
def populate_feedstock_attributes(
    name: str,
    sub_graph: LazyJson,
    meta_yaml: typing.Union[str, Response] = "",
    conda_forge_yaml: typing.Union[str, Response] = "",
    mark_not_archived=False,
    feedstock_dir=None,
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

    if mark_not_archived:
        sub_graph.update({"archived": False})

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

    if (
        feedstock_dir is not None
        and len(glob.glob(os.path.join(feedstock_dir, ".ci_support", "*.yaml"))) > 0
    ):
        recipe_dir = os.path.join(feedstock_dir, "recipe")
        ci_support_files = glob.glob(
            os.path.join(feedstock_dir, ".ci_support", "*.yaml"),
        )
        varient_yamls = []
        plat_arch = []
        for cbc_path in ci_support_files:
            cbc_name = os.path.basename(cbc_path)
            cbc_name_parts = cbc_name.replace(".yaml", "").split("_")
            plat = cbc_name_parts[0]
            if len(cbc_name_parts) == 1:
                arch = "64"
            else:
                if cbc_name_parts[1] in ["64", "aarch64", "ppc64le"]:
                    arch = cbc_name_parts[1]
                else:
                    arch = "64"
            plat_arch.append((plat, arch))

            varient_yamls.append(
                parse_meta_yaml(
                    meta_yaml,
                    platform=plat,
                    arch=arch,
                    recipe_dir=recipe_dir,
                    cbc_path=cbc_path,
                ),
            )

            # collapse them down
            final_cfgs = {}
            for plat_arch, varyml in zip(plat_arch, varient_yamls):
                if plat_arch not in final_cfgs:
                    final_cfgs[plat_arch] = []
                final_cfgs[plat_arch].append(varyml)
            for k in final_cfgs:
                ymls = final_cfgs[k]
                final_cfgs[k] = _convert_to_dict(ChainDB(*ymls))
            plat_arch = []
            varient_yamls = []
            for k, v in final_cfgs.items():
                plat_arch.append(k)
                varient_yamls.append(v)
    else:
        plat_arch = [("win", "64"), ("osx", "64"), ("linux", "64")]
        for k in set(sub_graph["conda-forge.yml"].get("provider", {})):
            if "_" in k:
                plat_arch.append(k.split("_"))
        varient_yamls = [
            parse_meta_yaml(meta_yaml, platform=plat, arch=arch)
            for plat, arch in plat_arch
        ]

    yaml_dict = ChainDB(*varient_yamls)
    if not yaml_dict:
        logger.error(f"Something odd happened when parsing recipe {name}")
        sub_graph["bad"] = "make_graph: Could not parse"
        return sub_graph

    sub_graph["meta_yaml"] = _convert_to_dict(yaml_dict)
    meta_yaml = sub_graph["meta_yaml"]

    for k, v in zip(plat_arch, varient_yamls):
        plat_arch_name = "_".join(k)
        sub_graph[f"{plat_arch_name}_meta_yaml"] = v
        _, sub_graph[f"{plat_arch_name}_requirements"], _ = extract_requirements(v)

    (
        sub_graph["total_requirements"],
        sub_graph["requirements"],
        sub_graph["strong_exports"],
    ) = extract_requirements(meta_yaml)

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
    for k in keys:
        if k[1] not in missing_keys:
            sub_graph[k[1]] = yaml_dict[k[0]][k[1]]
    kl = list(sorted(source_keys & hashlib.algorithms_available, reverse=True))
    if kl:
        sub_graph["hash_type"] = kl[0]
    return sub_graph


def get_attrs(name: str, i: int, mark_not_archived=False) -> LazyJson:
    try:
        # pull down one copy of the repo
        with tempfile.TemporaryDirectory() as tmpdir:
            feedstock_dir = _fetch_static_repo(name, tmpdir)

            with open(os.path.join(feedstock_dir, "recipe", "meta.yaml"), "r") as fp:
                meta_yaml = fp.read()

            with open(os.path.join(feedstock_dir, "conda-forge.yml"), "r") as fp:
                conda_forge_yaml = fp.read()

            lzj = LazyJson(f"node_attrs/{name}.json")
            with lzj as sub_graph:
                populate_feedstock_attributes(
                    name,
                    sub_graph,
                    meta_yaml=meta_yaml,
                    conda_forge_yaml=conda_forge_yaml,
                    mark_not_archived=mark_not_archived,
                    feedstock_dir=feedstock_dir,
                )
        return lzj
    except Exception:
        return None


def _build_graph_process_pool(
    gx: nx.DiGraph, names: List[str], new_names: List[str], mark_not_archived=False,
) -> None:

    # keeping this here for testing and posterity
    # jobs = [
    #     joblib.delayed(get_attrs)(name, i, mark_not_archived=mark_not_archived)
    #     for i, name in enumerate(names)
    # ]
    #
    # with joblib.Parallel(n_jobs=16, verbose=100) as p:
    #     attrs = p(jobs)
    #
    # for name, payload in zip(names, attrs):
    #     if payload is not None:
    #         sub_graph = {"payload": payload}
    #         if name in new_names:
    #             gx.add_node(name, **sub_graph)
    #         else:
    #             gx.nodes[name].update(**sub_graph)

    with executor("thread", max_workers=20) as pool:
        futures = {}
        for i, name in enumerate(names):
            f = pool.submit(get_attrs, name, i, mark_not_archived=mark_not_archived)
            futures[f] = name
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
                payload = f.result()
                if payload is not None:
                    sub_graph = {"payload": payload}
                if n_left % 100 == 0:
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
    gx: nx.DiGraph, names: List[str], new_names: List[str], mark_not_archived=False,
) -> None:
    for i, name in enumerate(names):
        try:
            sub_graph = {
                "payload": get_attrs(name, i, mark_not_archived=mark_not_archived),
            }
        except Exception as e:
            logger.error(f"Error adding {name} to the graph: {e}")
        else:
            if name in new_names:
                gx.add_node(name, **sub_graph)
            else:
                gx.nodes[name].update(**sub_graph)


def make_graph(
    names: List[str], gx: Optional[nx.DiGraph] = None, mark_not_archived=False,
) -> nx.DiGraph:
    logger.info("reading graph")

    if gx is None:
        gx = nx.DiGraph()

    new_names = [name for name in names if name not in gx.nodes]
    old_names = [name for name in names if name in gx.nodes]
    # silly typing force
    assert gx is not None
    old_names = sorted(  # type: ignore
        old_names, key=lambda n: gx.nodes[n].get("time", 0),
    )  # type: ignore

    total_names = new_names + old_names
    logger.info("start feedstock fetch loop")
    from .xonsh_utils import env

    debug = env.get("CONDA_FORGE_TICK_DEBUG", False)
    builder = _build_graph_sequential if debug else _build_graph_process_pool
    builder(gx, total_names, new_names, mark_not_archived=mark_not_archived)
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
                ),
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
    logger.info("new nodes and edges inferred")
    return gx


def update_nodes_with_bot_rerun(gx):
    """Go through all the open PRs and check if they are rerun"""
    for name, node in gx.nodes.items():
        with node["payload"] as payload:
            for migration in payload.get("PRed", []):
                pr_json = migration.get("PR", {})
                # if there is a valid PR and it isn't currently listed as rerun
                # but the PR needs a rerun
                if (
                    pr_json
                    and not migration["data"]["bot_rerun"]
                    and "bot-rerun" in [lb["name"] for lb in pr_json.get("labels", [])]
                ):
                    migration["data"]["bot_rerun"] = time.time()
                    logger.info(
                        "BOT-RERUN %s: processing bot rerun label for migration %s",
                        name,
                        migration["data"],
                    )


def update_nodes_with_new_versions(gx):
    """Updates every node with it's new version (when available)"""
    # check if the versions folder is available
    if os.path.isdir("./versions"):
        pass
    else:
        return
    # get all the available node.json files
    # TODO: I don't thing this is a good idea (8000+ entries)
    list_files = os.listdir("./versions/")

    for file in list_files:
        node = str(file).replace(".json", "")
        with open(f"./versions/{file}") as json_file:
            version_data = json.load(json_file)
        with gx.nodes[f"{node}"]["payload"] as attrs:
            attrs.update(version_data)


def main(args: "CLIArgs") -> None:
    setup_logger(logger)

    mark_not_archived = False
    if os.path.exists("names_are_active.flag"):
        with open("names_are_active.flag", "r") as fp:
            if fp.read().strip() == "yes":
                mark_not_archived = True

    names = get_all_feedstocks(cached=True)
    if os.path.exists("graph.json"):
        gx = load_graph()
    else:
        gx = None
    gx = make_graph(names, gx, mark_not_archived=mark_not_archived)
    print(
        "nodes w/o payload:", [k for k, v in gx.nodes.items() if "payload" not in v],
    )
    update_nodes_with_bot_rerun(gx)
    update_nodes_with_new_versions(gx)

    dump_graph(gx)


if __name__ == "__main__":
    pass
    # main()
