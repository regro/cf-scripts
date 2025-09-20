import hashlib
import logging
import re
import secrets
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
    LAZY_JSON_BACKENDS,
    LazyJson,
    get_lazy_json_backends,
    lazy_json_override_backends,
    lazy_json_transaction,
)

from .all_feedstocks import get_all_feedstocks, get_archived_feedstocks
from .cli_context import CliContext
from .executors import executor
from .settings import settings
from .utils import (
    as_iterable,
    dump_graph,
    load_existing_graph,
    load_graph,
    sanitize_string,
)

# from conda_forge_tick.profiler import profiling


logger = logging.getLogger(__name__)

pin_sep_pat = re.compile(r" |>|<|=|\[")
RNG = secrets.SystemRandom()

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


def _add_required_lazy_json_refs(attrs, name):
    for sub_lzj in ["version_pr_info", "pr_info"]:
        if sub_lzj not in attrs:
            attrs[sub_lzj] = LazyJson(f"{sub_lzj}/{name}.json")

    with attrs["version_pr_info"] as vpri:
        for key in [
            "new_version_attempts",
            "new_version_errors",
            "new_version_attempt_ts",
        ]:
            if key not in vpri:
                vpri[key] = {}

    with attrs["pr_info"] as pri:
        for key in [
            "pre_pr_migrator_status",
            "pre_pr_migrator_attempts",
            "pre_pr_migrator_attempt_ts",
        ]:
            if key not in pri:
                pri[key] = {}


def try_load_feedstock(name: str, attrs: LazyJson, mark_not_archived=False) -> LazyJson:
    try:
        data = load_feedstock(name, attrs.data, mark_not_archived=mark_not_archived)
        if "parsing_error" not in data:
            data["parsing_error"] = False
        attrs.clear()
        attrs.update(data)
    except Exception as e:
        import traceback

        trb = traceback.format_exc()
        attrs["parsing_error"] = sanitize_string(f"feedstock parsing error: {e}\n{trb}")
    finally:
        _add_required_lazy_json_refs(attrs, name)

    return attrs


def get_attrs(name: str, mark_not_archived=False) -> LazyJson:
    lzj = LazyJson(f"node_attrs/{name}.json")
    with lzj as sub_graph:
        try_load_feedstock(name, sub_graph, mark_not_archived=mark_not_archived)

    return lzj


def _migrate_schema(name, sub_graph):
    # schema migrations and fixes go here
    with lazy_json_transaction():
        _add_required_lazy_json_refs(sub_graph, name)

    if "last_updated" in sub_graph:
        with lazy_json_transaction():
            sub_graph.pop("last_updated")

    vpri_move_keys = [
        "new_version_attempts",
        "new_version_errors",
        "new_version_attempt_ts",
    ]
    if any(key in sub_graph for key in vpri_move_keys):
        with lazy_json_transaction():
            with sub_graph["version_pr_info"] as vpri:
                for key in vpri_move_keys:
                    if key in sub_graph:
                        vpri[key].update(sub_graph.pop(key))

    if "new_version" in sub_graph:
        with lazy_json_transaction():
            with sub_graph["version_pr_info"] as vpri:
                vpri["new_version"] = sub_graph.pop("new_version")

    pre_key = "pre_pr_migrator_status"
    pre_key_att = "pre_pr_migrator_attempts"
    pre_key_att_ts = "pre_pr_migrator_attempt_ts"
    pri_move_keys = [pre_key, pre_key_att, pre_key_att_ts]
    if any(key in sub_graph for key in pri_move_keys):
        with lazy_json_transaction():
            with sub_graph["pr_info"] as pri:
                for key in pri_move_keys:
                    if key in sub_graph:
                        pri[key].update(sub_graph.pop(key))

                # populate migrator attempts if they are not there
                for mn in pri[pre_key]:
                    if mn not in pri[pre_key_att]:
                        pri[pre_key_att][mn] = 1

    with lazy_json_transaction():
        with sub_graph["pr_info"] as pri:
            for mn in pri[pre_key].keys():
                if mn not in pri[pre_key_att]:
                    pri[pre_key_att][mn] = 1
                if mn not in pri[pre_key_att_ts]:
                    # set the attempt to one hour ago
                    pri[pre_key_att_ts][mn] = int(time.time()) - 3600.0

        with sub_graph["version_pr_info"] as vpri:
            for mn in vpri["new_version_errors"].keys():
                if mn not in vpri["new_version_attempts"]:
                    vpri["new_version_attempts"][mn] = 1
                if mn not in vpri["new_version_attempt_ts"]:
                    # set the attempt to one hour ago
                    vpri["new_version_attempt_ts"][mn] = int(time.time()) - 3600.0

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
        with lazy_json_transaction():
            sub_graph["parsing_error"] = "make_graph: missing parsing_error key"


def _build_graph_process_pool(
    names: List[str],
    mark_not_archived=False,
) -> None:
    # we use threads here since all of the work is done in a container anyways
    with executor("thread", max_workers=8) as pool:
        futures = {
            pool.submit(get_attrs, name, mark_not_archived=mark_not_archived): name
            for name in names
            if RNG.random() <= settings().frac_make_graph
        }
        logger.info("submitted all nodes")

        n_tot = len(futures)
        n_left = len(futures)
        start = time.time()
        eta = -1.0
        for f in as_completed(futures):
            n_left -= 1
            if n_left % 10 == 0:
                eta = (time.time() - start) / (n_tot - n_left) * n_left
            name = futures[f]
            try:
                f.result()
                if n_left % 100 == 0:
                    logger.info(
                        "nodes left %5d - eta %5ds: finished %s", n_left, int(eta), name
                    )
            except Exception as e:
                logger.error(
                    "nodes left %5d - eta %5ds: error adding %s to the graph",
                    n_left,
                    int(eta),
                    name,
                    exc_info=e,
                )


def _build_graph_sequential(
    names: List[str],
    mark_not_archived=False,
) -> None:
    for name in names:
        if RNG.random() > settings().frac_make_graph:
            logger.debug("skipping %s due to random fraction to update", name)
            continue

        try:
            get_attrs(name, mark_not_archived=mark_not_archived)
        except Exception as e:
            logger.error("Error updating node %s", name, exc_info=e)


def _get_all_deps_for_node(attrs, outputs_lut):
    # replace output package names with feedstock names via LUT
    deps = set()
    for req_section in attrs.get("requirements", {}).values():
        deps.update(
            get_deps_from_outputs_lut(req_section, outputs_lut),
        )

    return deps


def _add_run_exports_per_node(attrs, outputs_lut, strong_exports):
    deps = _get_all_deps_for_node(attrs, outputs_lut)

    # handle strong run exports
    # TODO: do this per platform
    overlap = deps & strong_exports
    requirements = attrs.get("requirements")
    if requirements and overlap:
        requirements["host"].update(overlap)
        requirements["run"].update(overlap)

    return deps


def _create_edges(gx: nx.DiGraph) -> nx.DiGraph:
    logger.info("inferring nodes and edges")

    # This drops all the edge data and only keeps the node data
    gx = nx.create_empty_copy(gx)

    # TODO: label these edges with the kind of dep they are and their platform
    # use a list so we don't change an iterable that is iterating
    all_nodes = list(gx.nodes.keys())
    for node in all_nodes:
        with gx.nodes[node]["payload"] as attrs:
            deps = _get_all_deps_for_node(attrs, gx.graph["outputs_lut"])

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


def _add_graph_metadata(gx: nx.DiGraph):
    logger.info("adding graph metadata")

    # make the outputs look up table so we can link properly
    # and add this as an attr so we can use later
    gx.graph["outputs_lut"] = make_outputs_lut_from_graph(gx)

    # collect all of the strong run exports
    # we add the compiler stubs so that we know when host and run
    # envs will have compiler-related packages in them
    gx.graph["strong_exports"] = {
        node_name
        for node_name, node in gx.nodes.items()
        if node.get("payload").get("strong_exports", False)
    } | set(COMPILER_STUBS_WITH_STRONG_EXPORTS)


def _add_run_exports(gx: nx.DiGraph, nodes_to_update: set[str]):
    logger.info("adding run exports")

    for node in nodes_to_update:
        if node not in gx.nodes:
            continue
        with gx.nodes[node]["payload"] as attrs:
            _add_run_exports_per_node(
                attrs, gx.graph["outputs_lut"], gx.graph["strong_exports"]
            )


def _update_graph_nodes(
    names: List[str],
    mark_not_archived=False,
    debug=False,
) -> nx.DiGraph:
    logger.info("start feedstock fetch loop")
    builder = _build_graph_sequential if debug else _build_graph_process_pool
    builder(
        names,
        mark_not_archived=mark_not_archived,
    )
    logger.info("feedstock fetch loop completed")
    logger.info("memory usage: %s", psutil.virtual_memory())


def _update_nodes_with_archived(names):
    for name in names:
        with LazyJson(f"node_attrs/{name}.json") as sub_graph:
            sub_graph["archived"] = True


def _migrate_schemas(nodes):
    for node in tqdm.tqdm(nodes, desc="migrating node schemas", miniters=100, ncols=80):
        with LazyJson(f"node_attrs/{node}.json") as sub_graph:
            _migrate_schema(node, sub_graph)


def main(
    ctx: CliContext,
    job: int = 1,
    n_jobs: int = 1,
    update_nodes_and_edges: bool = False,
    schema_migration_only: bool = False,
) -> None:
    logger.info("getting all nodes")
    names = get_all_feedstocks(cached=True)
    archived_names = get_archived_feedstocks(cached=True)
    tot_names = set(names) | set(archived_names)
    for backend_name in get_lazy_json_backends():
        backend = LAZY_JSON_BACKENDS[backend_name]()
        tot_names |= set(backend.hkeys("node_attrs"))

    tot_names_for_this_job = _get_names_for_job(tot_names, job, n_jobs)
    names_for_this_job = _get_names_for_job(names, job, n_jobs)
    archived_names_for_this_job = _get_names_for_job(archived_names, job, n_jobs)
    logger.info("total # of nodes across all backends: %d", len(tot_names))
    logger.info("active nodes: %d", len(names))
    logger.info("archived nodes: %d", len(archived_names))

    if update_nodes_and_edges:
        gx = load_existing_graph()

        new_names = [name for name in names if name not in gx.nodes]
        for name in names:
            sub_graph = {
                "payload": LazyJson(f"node_attrs/{name}.json"),
            }
            if name in new_names:
                gx.add_node(name, **sub_graph)
            else:
                gx.nodes[name].update(**sub_graph)

        _add_graph_metadata(gx)

        gx = _create_edges(gx)

        dump_graph(gx)

    else:
        gx = load_graph()

        with lazy_json_override_backends(
            ["file"],
            hashmaps_to_sync=["node_attrs"],
            keys_to_sync=set(tot_names_for_this_job),
        ):
            if schema_migration_only:
                _migrate_schemas(tot_names_for_this_job)
            else:
                _update_graph_nodes(
                    names_for_this_job,
                    mark_not_archived=True,
                    debug=ctx.debug,
                )
                _add_run_exports(gx, names_for_this_job)

                _update_nodes_with_archived(
                    archived_names_for_this_job,
                )
