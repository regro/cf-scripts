import logging
import os
import re
import time
import typing
import traceback
from concurrent.futures import as_completed
from collections import defaultdict
import random

import tqdm
from typing import List, Optional, Iterable
import psutil
import networkx as nx

# from conda_forge_tick.profiler import profiling

from conda_forge_tick.feedstock_parser import load_feedstock
from .all_feedstocks import get_all_feedstocks, get_archived_feedstocks
from .contexts import GithubContext
from .executors import executor
from .utils import (
    setup_logger,
    load_graph,
    dump_graph,
    as_iterable,
)
from . import sensitive_env
from conda_forge_tick.lazy_json_backends import LazyJson, get_all_keys_for_hashmap

if typing.TYPE_CHECKING:
    from .cli import CLIArgs

LOGGER = logging.getLogger("conda_forge_tick.make_graph")
pin_sep_pat = re.compile(r" |>|<|=|\[")
random.seed(os.urandom(64))

RANDOM_FRAC_TO_UPDATE = 1.5
NUM_GITHUB_THREADS = 2

with sensitive_env() as env:
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


def get_deps_from_outputs_lut(
    req_section: Iterable,
    outputs_lut: typing.Dict[str, set],
) -> set:
    deps = set()
    for req in req_section:
        i = as_iterable(outputs_lut.get(req, req))
        deps.update(i)
    return deps


def make_outputs_lut_from_graph(gx):
    outputs_lut = defaultdict(set)
    for node_name, node in gx.nodes.items():
        for k in node.get("payload", {}).get("outputs_names", []):
            if node_name != "pypy-meta" and node_name != "graalpy":
                outputs_lut[k].add(node_name)
            elif k in ["pypy", "graalpy"]:
                # for pypy-meta we only map to pypy and not python or cffi
                # for graalpy we only map to graalpy and not python or openjdk
                outputs_lut[k].add(node_name)
    return outputs_lut


def get_attrs(name: str, i: int, mark_not_archived=False) -> LazyJson:
    lzj = LazyJson(f"node_attrs/{name}.json")
    with lzj as sub_graph:
        load_feedstock(name, sub_graph, mark_not_archived=mark_not_archived)

    return lzj


def _migrate_schema(name, sub_graph):
    # schema migrations and fixes go here
    if "version_pr_info" not in sub_graph:
        sub_graph["version_pr_info"] = LazyJson(f"version_pr_info/{name}.json")
        with sub_graph["version_pr_info"] as vpri:
            for key in ["new_version_attempts", "new_version_errors"]:
                if key not in vpri:
                    vpri[key] = {}
                if key in sub_graph:
                    vpri[key].update(sub_graph.pop(key))

    if "new_version" in sub_graph:
        with sub_graph["version_pr_info"] as vpri:
            vpri["new_version"] = sub_graph.pop("new_version")

    if "pr_info" not in sub_graph:
        sub_graph["pr_info"] = LazyJson(f"pr_info/{name}.json")
        with sub_graph["pr_info"] as pri:
            pre_key = "pre_pr_migrator_status"
            pre_key_att = "pre_pr_migrator_attempts"

            for key in [pre_key, pre_key_att]:
                if key not in pri:
                    pri[key] = {}
                if key in sub_graph:
                    pri[key].update(sub_graph.pop(key))

            # populate migrator attempts if they are not there
            for mn in pri[pre_key]:
                if mn not in pri[pre_key_att]:
                    pri[pre_key_att][mn] = 1

    keys_to_move = [
        "PRed",
        "smithy_version",
        "pinning_version",
        "bad",
    ]
    if any(key in sub_graph for key in keys_to_move):
        with sub_graph["pr_info"] as pri:
            for key in keys_to_move:
                if key in sub_graph:
                    pri[key] = sub_graph.pop(key)
                    if key == "bad":
                        pri["bad"] = False

    if "parsing_error" not in sub_graph:
        sub_graph["parsing_error"] = "make_graph: missing parsing_error key"


def _build_graph_process_pool(
    gx: nx.DiGraph,
    names: List[str],
    new_names: List[str],
    mark_not_archived=False,
) -> None:
    with executor("process", max_workers=8) as pool:
        futures = {
            pool.submit(get_attrs, name, i, mark_not_archived=mark_not_archived): name
            for i, name in enumerate(names)
            if random.uniform(0, 1) < RANDOM_FRAC_TO_UPDATE
        }
        LOGGER.info("submitted all nodes")

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
                    LOGGER.info("itr % 5d - eta % 5ds: finished %s", n_left, eta, name)
            except Exception as e:
                LOGGER.error(
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
            trb = traceback.format_exc()
            LOGGER.error(f"Error adding {name} to the graph: {e}\n{trb}")
        else:
            if name in new_names:
                gx.add_node(name, **sub_graph)
            else:
                gx.nodes[name].update(**sub_graph)


def _create_edges(gx: nx.DiGraph) -> nx.DiGraph:
    LOGGER.info("inferring nodes and edges")

    # make the outputs look up table so we can link properly
    # and add this as an attr so we can use later
    gx.graph["outputs_lut"] = make_outputs_lut_from_graph(gx)

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
            deps = set()
            for req_section in attrs.get("requirements", {}).values():
                deps.update(
                    get_deps_from_outputs_lut(req_section, gx.graph["outputs_lut"]),
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
                with lzj as attrs:
                    attrs.update(feedstock_name=dep, bad=False, archived=True)
                gx.add_node(dep, payload=lzj)
            gx.add_edge(dep, node)
    LOGGER.info("new nodes and edges inferred")

    return gx


def make_graph(
    names: List[str],
    gx: Optional[nx.DiGraph] = None,
    mark_not_archived=False,
    debug=False,
) -> nx.DiGraph:
    LOGGER.info("reading graph")

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

    LOGGER.info("start feedstock fetch loop")
    builder = _build_graph_sequential if debug else _build_graph_process_pool
    builder(gx, total_names, new_names, mark_not_archived=mark_not_archived)
    LOGGER.info("feedstock fetch loop completed")

    gx = _create_edges(gx)

    LOGGER.info(f"memory usage: {psutil.virtual_memory()}")
    return gx


def _update_nodes_with_archived(gx, archived_names):
    for name in archived_names:
        if name in gx.nodes:
            node = gx.nodes[name]
            with node["payload"] as payload:
                payload["archived"] = True


def _migrate_schemas():
    # make sure to apply all schema migrations
    nodes = get_all_keys_for_hashmap("node_attrs")
    for node in tqdm.tqdm(nodes, desc="migrating node schemas", miniters=100, ncols=80):
        with LazyJson(f"node_attrs/{node}.json") as sub_graph:
            _migrate_schema(node, sub_graph)


# @profiling
def main(args: "CLIArgs") -> None:
    if args.debug:
        setup_logger(logging.getLogger("conda_forge_tick"), level="debug")
    else:
        setup_logger(logging.getLogger("conda_forge_tick"))

    names = get_all_feedstocks(cached=True)
    gx = load_graph()

    gx = make_graph(names, gx, mark_not_archived=True, debug=args.debug)
    nodes_without_paylod = [k for k, v in gx.nodes.items() if "payload" not in v]
    if nodes_without_paylod:
        LOGGER.warning("nodes w/o payload: %s", nodes_without_paylod)

    _migrate_schemas()

    archived_names = get_archived_feedstocks(cached=True)
    _update_nodes_with_archived(gx, archived_names)

    dump_graph(gx)


if __name__ == "__main__":
    pass
    # main()
