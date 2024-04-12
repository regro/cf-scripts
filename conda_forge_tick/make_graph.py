import hashlib
import logging
import os
import random
import re
import time
import typing
from collections import defaultdict
from concurrent.futures import as_completed
from typing import Iterable, List

import networkx as nx
import psutil
import tqdm

from conda_forge_tick.feedstock_parser import load_feedstock
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    get_all_keys_for_hashmap,
    lazy_json_override_backends,
    lazy_json_transaction,
)

from .all_feedstocks import get_all_feedstocks, get_archived_feedstocks
from .cli_context import CliContext
from .executors import executor
from .utils import as_iterable, dump_graph, load_graph

# from conda_forge_tick.profiler import profiling


logger = logging.getLogger(__name__)

pin_sep_pat = re.compile(r" |>|<|=|\[")
random.seed(os.urandom(64))

RANDOM_FRAC_TO_UPDATE = 0.2

# AFAIK, go and rust do not have strong run exports and so do not need to
# appear here
COMPILER_STUBS_WITH_STRONG_EXPORTS = [
    "c_compiler_stub",
    "c_stdlib_stub",
    "cxx_compiler_stub",
    "fortran_compiler_stub",
    "cuda_compiler_stub",
]


def _get_names_for_job(names, job, n_jobs):
    job_index = job - 1
    return [
        node_id
        for node_id in names
        if abs(int(hashlib.sha1(node_id.encode("utf-8")).hexdigest(), 16)) % n_jobs
        == job_index
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
        data = load_feedstock(name, sub_graph.data, mark_not_archived=mark_not_archived)
        sub_graph.update(data)

    return lzj


def _migrate_schema(name, sub_graph):
    # schema migrations and fixes go here
    if "version_pr_info" not in sub_graph:
        with lazy_json_transaction():
            sub_graph["version_pr_info"] = LazyJson(f"version_pr_info/{name}.json")
            with sub_graph["version_pr_info"] as vpri:
                for key in ["new_version_attempts", "new_version_errors"]:
                    if key not in vpri:
                        vpri[key] = {}
                    if key in sub_graph:
                        vpri[key].update(sub_graph.pop(key))

    if "new_version" in sub_graph:
        with lazy_json_transaction():
            with sub_graph["version_pr_info"] as vpri:
                vpri["new_version"] = sub_graph.pop("new_version")

    if "pr_info" not in sub_graph:
        with lazy_json_transaction():
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
        with lazy_json_transaction():
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
    job: int = 1,
    n_jobs: int = 1,
) -> None:
    # we use threads here since all of the work is done in a container anyways
    with executor("thread", max_workers=8) as pool:
        futures = {
            pool.submit(get_attrs, name, i, mark_not_archived=mark_not_archived): name
            for i, name in enumerate(names)
            if random.uniform(0, 1) < RANDOM_FRAC_TO_UPDATE
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
                f.result()
                if n_left % 100 == 0:
                    logger.info("itr % 5d - eta % 5ds: finished %s", n_left, eta, name)
            except Exception as e:
                logger.error(
                    f"itr {n_left: 5d} - eta {eta: 5d}s: Error adding {name} to the graph",
                    exc_info=e,
                )


def _build_graph_sequential(
    names: List[str],
    mark_not_archived=False,
    job: int = 1,
    n_jobs: int = 1,
) -> None:
    for i, name in enumerate(names):
        if random.uniform(0, 1) >= RANDOM_FRAC_TO_UPDATE:
            continue

        try:
            get_attrs(name, i, mark_not_archived=mark_not_archived)
        except Exception as e:
            logger.error(f"Error updating node {name}", exc_info=e)


def _create_edges(gx: nx.DiGraph) -> nx.DiGraph:
    logger.info("inferring nodes and edges")

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
                with lzj as _attrs:
                    _attrs.update(feedstock_name=dep, bad=False, archived=True)
                gx.add_node(dep, payload=lzj)
            gx.add_edge(dep, node)
    logger.info("new nodes and edges inferred")

    return gx


def _update_graph_nodea(
    names: List[str],
    mark_not_archived=False,
    debug=False,
    job: int = 1,
    n_jobs: int = 1,
) -> nx.DiGraph:
    _names_to_update = _get_names_for_job(names, job, n_jobs)

    logger.info("start feedstock fetch loop")
    builder = _build_graph_sequential if debug else _build_graph_process_pool
    builder(
        _names_to_update, mark_not_archived=mark_not_archived, job=job, n_jobs=n_jobs
    )
    logger.info("feedstock fetch loop completed")

    logger.info(f"memory usage: {psutil.virtual_memory()}")


def _update_nodes_with_archived(archived_names, job: int = 1, n_jobs: int = 1):
    _names_to_update = _get_names_for_job(archived_names, job, n_jobs)
    for name in _names_to_update:
        with LazyJson(f"node_attrs/{name}.json") as sub_graph:
            sub_graph["archived"] = True


def _migrate_schemas(job: int = 1, n_jobs: int = 1):
    # make sure to apply all schema migrations, not just those in the graph
    nodes = get_all_keys_for_hashmap("node_attrs")

    _names_to_update = _get_names_for_job(nodes, job, n_jobs)

    for node in tqdm.tqdm(
        _names_to_update, desc="migrating node schemas", miniters=100, ncols=80
    ):
        with LazyJson(f"node_attrs/{node}.json") as sub_graph:
            _migrate_schema(node, sub_graph)


# @profiling
def main(
    ctx: CliContext, job: int = 1, n_jobs: int = 1, update_nodes_and_edges: bool = False
) -> None:
    if update_nodes_and_edges:
        gx = load_graph()

        names = get_all_keys_for_hashmap("node_attrs")
        new_names = [name for name in names if name not in gx.nodes]

        for name in names:
            sub_graph = {
                "payload": LazyJson(f"node_attrs/{name}.json"),
            }
            if name in new_names:
                gx.add_node(name, **sub_graph)
            else:
                gx.nodes[name].update(**sub_graph)

        gx = _create_edges(gx)

        dump_graph(gx)
    else:
        names = get_all_feedstocks(cached=True)
        names_for_this_job = _get_names_for_job(names, job, n_jobs)

        with lazy_json_override_backends(
            ["file"],
            hashmaps_to_sync=["node_attrs"],
            keys_to_sync=set(names_for_this_job),
        ):
            _update_graph_nodea(
                names, mark_not_archived=True, debug=ctx.debug, job=job, n_jobs=n_jobs
            )

            archived_names = get_archived_feedstocks(cached=True)
            _update_nodes_with_archived(archived_names, job=job, n_jobs=n_jobs)

            _migrate_schemas(job=job, n_jobs=n_jobs)
