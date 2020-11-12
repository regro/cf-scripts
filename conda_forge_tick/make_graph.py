import logging
import os
import re
import time
import typing
import random
from concurrent.futures import as_completed

from typing import List, Optional
import psutil
import json
import networkx as nx
import requests
from conda.models.version import VersionOrder
from requests import Response

# from conda_forge_tick.profiler import profiling

from conda_forge_tick.utils import load_feedstock
from .all_feedstocks import get_all_feedstocks
from .contexts import GithubContext
from .utils import (
    setup_logger,
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

# AFAIK, go and rust do not have strong run exports and so do not need to
# appear here
COMPILER_STUBS_WITH_STRONG_EXPORTS = [
    "c_compiler_stub",
    "cxx_compiler_stub",
    "fortran_compiler_stub",
    "cuda_compiler_stub",
]


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


def get_attrs(name: str, i: int, mark_not_archived=False) -> LazyJson:
    lzj = LazyJson(f"node_attrs/{name}.json")
    with lzj as sub_graph:
        load_feedstock(name, sub_graph, mark_not_archived=mark_not_archived)
    return lzj


def _build_graph_process_pool(
    gx: nx.DiGraph,
    names: List[str],
    new_names: List[str],
    mark_not_archived=False,
) -> None:
    with executor("thread", max_workers=20) as pool:
        futures = {
            pool.submit(get_attrs, name, i, mark_not_archived=mark_not_archived): name
            for i, name in enumerate(names)
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
    gx: nx.DiGraph,
    names: List[str],
    new_names: List[str],
    mark_not_archived=False,
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
    names: List[str],
    gx: Optional[nx.DiGraph] = None,
    mark_not_archived=False,
) -> nx.DiGraph:
    logger.info("reading graph")

    if gx is None:
        gx = nx.DiGraph()

    new_names = [name for name in names if name not in gx.nodes]
    old_names = [name for name in names if name in gx.nodes]
    # silly typing force
    assert gx is not None
    old_names = sorted(  # type: ignore
        old_names,
        key=lambda n: gx.nodes[n].get("time", 0),
    )  # type: ignore

    total_names = new_names + old_names
    logger.info("start feedstock fetch loop")
    from .xonsh_utils import env

    debug = env.get("CONDA_FORGE_TICK_DEBUG", False)
    builder = _build_graph_sequential if debug else _build_graph_process_pool
    builder(gx, total_names, new_names, mark_not_archived=mark_not_archived)
    logger.info("feedstock fetch loop completed")

    logger.info("inferring nodes and edges")

    # make the outputs look up table so we can link properly
    # and add this as an attr so we can use later
    outputs_lut = {}
    for node_name, node in gx.nodes.items():
        for k in node.get("payload", {}).get("outputs_names", []):
            if node_name != "pypy-meta":
                outputs_lut[k] = node_name
            elif k == "pypy":
                # for pypy-meta we only map to pypy and not python or cffi
                outputs_lut[k] = node_name
    gx.graph["outputs_lut"] = outputs_lut

    # collect all of the strong run exports
    # we add the compiler stubs so that we know when host and run
    # envs will have compiler-related packages in them
    strong_exports = {
        node_name
        for node_name, node in gx.nodes.items()
        if node.get("payload").get("strong_exports", False)
    } | set(COMPILER_STUBS_WITH_STRONG_EXPORTS)

    # This drops all the edge data and only keeps the node data
    gx = nx.create_empty_copy(gx)

    # TODO: label these edges with the kind of dep they are and their platform
    # use a list so we don't change an iterable that is iterating
    all_nodes = list(gx.nodes.keys())
    for node in all_nodes:
        with gx.nodes[node]["payload"] as attrs:
            # replace output package names with feedstock names via LUT
            deps = set(
                map(
                    lambda x: outputs_lut.get(x, x),
                    set().union(*attrs.get("requirements", {}).values()),
                ),
            )

            # handle strong run exports
            # TODO: do this per platform
            overlap = deps & strong_exports
            requirements = attrs.get("requirements")
            if requirements and overlap:
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
    logger.info(f"memory usage: {psutil.virtual_memory()}")
    return gx


def update_nodes_with_bot_rerun(gx):
    """Go through all the open PRs and check if they are rerun"""
    for i, (name, node) in enumerate(gx.nodes.items()):
        # logger.info(
        #     f"node: {i} memory usage: "
        #     f"{psutil.Process().memory_info().rss // 1024 ** 2}MB",
        # )
        with node["payload"] as payload:
            for migration in payload.get("PRed", []):
                if random.random() >= 0.5:
                    continue
                try:
                    pr_json = migration.get("PR", {})
                    # maybe add a pass check info here ? (if using DEBUG)
                except Exception as e:
                    logger.error(
                        f"BOT-RERUN : could not proceed check with {node}, {e}",
                    )
                    raise e
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
            version_data: typing.Dict = json.load(json_file)
        with gx.nodes[f"{node}"]["payload"] as attrs:
            version_from_data = version_data.get("new_version", False)
            version_from_attrs = attrs.get("new_version", False)
            # don't update the version if it isn't newer
            if version_from_data and isinstance(version_from_data, str):
                if isinstance(version_from_attrs, str):
                    version_update_data = {
                        "new_version": max(
                            [version_from_data, version_from_attrs],
                            key=lambda x: VersionOrder(x.replace("-", ".")),
                        ),
                    }
                    attrs.update(version_update_data)


# @profiling
def main(args: "CLIArgs") -> None:
    setup_logger(logger)

    mark_not_archived = False
    if os.path.exists("names_are_active.flag"):
        with open("names_are_active.flag") as fp:
            if fp.read().strip() == "yes":
                mark_not_archived = True

    names = get_all_feedstocks(cached=True)
    if os.path.exists("graph.json"):
        gx = load_graph()
    else:
        gx = None
    gx = make_graph(names, gx, mark_not_archived=mark_not_archived)
    print(
        "nodes w/o payload:",
        [k for k, v in gx.nodes.items() if "payload" not in v],
    )
    update_nodes_with_bot_rerun(gx)
    update_nodes_with_new_versions(gx)

    dump_graph(gx)


if __name__ == "__main__":
    pass
    # main()
