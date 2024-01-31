import networkx as nx
import logging
import random
import time
import os
import tqdm
import hashlib
from concurrent.futures import as_completed

from conda_forge_tick.cli_context import CliContext
from .lazy_json_backends import LazyJson
from .utils import setup_logger, load_graph
from .executors import executor
from .update_sources import (
    AbstractSource,
    PyPI,
    CRAN,
    NPM,
    ROSDistro,
    RawURL,
    Github,
    IncrementAlphaRawURL,
    NVIDIA,
)
from typing import Any, Iterable
from .utils import get_keys_default

# conda_forge_tick :: cft
logger = logging.getLogger("conda_forge_tick.update_upstream_versions")


def _filter_ignored_versions(attrs, version):
    versions_to_ignore = get_keys_default(
        attrs,
        ["conda-forge.yml", "bot", "version_updates", "exclude"],
        {},
        [],
    )
    if (
        str(version).replace("-", ".") in versions_to_ignore
        or str(version) in versions_to_ignore
    ):
        return False
    else:
        return version


def get_latest_version(
    name: str,
    attrs: Any,
    sources: Iterable[AbstractSource],
) -> dict:
    version_data = {"new_version": False}

    # avoid this one since it runs too long and hangs the bot
    if name == "ca-policy-lcg":
        return version_data

    version_sources = get_keys_default(
        attrs,
        ["conda-forge.yml", "bot", "version_updates", "sources"],
        {},
        None,
    )
    if version_sources is not None:
        version_sources = [vs.lower() for vs in version_sources]
        sources_to_use = []
        for vs in version_sources:
            for source in sources:
                if source.name.lower() == vs:
                    sources_to_use.append(source)

        for source in sources:
            if source not in sources_to_use:
                logger.debug("skipped source: %s", source.name)
    else:
        sources_to_use = sources

    excs = []
    for source in sources_to_use:
        try:
            logger.debug("source: %s", source.name)
            url = source.get_url(attrs)
            logger.debug("url: %s", url)
            if url is None:
                continue
            ver = source.get_version(url)
            logger.debug("ver: %s", ver)
            if ver:
                version_data["new_version"] = ver
                break
            else:
                logger.debug(f"Upstream: Could not find version on {source.name}")
        except Exception as e:
            excs.append(e)

    if version_data["new_version"] is False and len(excs) > 0:
        raise excs[0]

    if version_data["new_version"]:
        version_data["new_version"] = _filter_ignored_versions(
            attrs,
            version_data["new_version"],
        )

    return version_data


def _filter_nodes_for_job(_all_nodes, job, n_jobs):
    job_index = job - 1
    return [
        t
        for t in _all_nodes
        if abs(int(hashlib.sha1(t[0].encode("utf-8")).hexdigest(), 16)) % n_jobs
        == job_index
    ]


def _update_upstream_versions_sequential(
    gx: nx.DiGraph,
    sources: Iterable[AbstractSource] = None,
    job=1,
    n_jobs=1,
) -> None:

    _all_nodes = [t for t in gx.nodes.items()]
    _all_nodes = _filter_nodes_for_job(
        _all_nodes,
        job,
        n_jobs,
    )
    random.shuffle(_all_nodes)

    # Inspection the graph object and node update:
    # print(f"Number of nodes: {len(gx.nodes)}")
    node_count = 0
    to_update = []
    for node, node_attrs in _all_nodes:
        attrs = node_attrs["payload"]
        pri = attrs.get("pr_info", {})
        if (
            attrs.get("parsing_error", False)
            or (pri.get("bad") and "Upstream" not in pri.get("bad"))
            or attrs.get("archived")
        ):
            continue
        to_update.append((node, attrs))

    for node, attrs in to_update:
        # checking each node
        version_data = {}

        # New version request
        try:
            # check for latest version
            version_data.update(get_latest_version(node, attrs, sources))
        except Exception as e:
            try:
                se = repr(e)
            except Exception as ee:
                se = f"Bad exception string: {ee}"
            logger.warning(f"Warning: Error getting upstream version of {node}: {se}")
            version_data["bad"] = "Upstream: Error getting upstream version"
        else:
            logger.info(
                f"# {node_count:<5} - {node} - {attrs.get('version')} "
                f"- {version_data.get('new_version')}",
            )

        logger.debug("writing out file")
        lzj = LazyJson(f"versions/{node}.json")
        with lzj as attrs:
            attrs.clear()
            attrs.update(version_data)
        node_count += 1


def _update_upstream_versions_process_pool(
    gx: nx.DiGraph,
    sources: Iterable[AbstractSource],
    job=1,
    n_jobs=1,
) -> None:
    futures = {}
    # this has to be threads because the url hashing code uses a Pipe which
    # cannot be spawned from a process
    with executor(kind="dask", max_workers=5) as pool:
        _all_nodes = [t for t in gx.nodes.items()]
        _all_nodes = _filter_nodes_for_job(
            _all_nodes,
            job,
            n_jobs,
        )
        random.shuffle(_all_nodes)

        for node, node_attrs in tqdm.tqdm(
            _all_nodes,
            ncols=80,
            desc="submitting version update jobs",
        ):
            attrs = node_attrs["payload"]
            pri = attrs.get("pr_info", {})
            if (
                attrs.get("parsing_error", False)
                or (pri.get("bad") and "Upstream" not in pri.get("bad"))
                or attrs.get("archived")
            ):
                continue

            futures.update(
                {
                    pool.submit(get_latest_version, node, attrs, sources): (
                        node,
                        attrs,
                    ),
                },
            )

        n_tot = len(futures)
        n_left = len(futures)
        start = time.time()
        # eta :: elapsed time average
        eta = -1
        for f in as_completed(futures):

            n_left -= 1
            if n_left % 10 == 0:
                eta = (time.time() - start) / (n_tot - n_left) * n_left

            node, attrs = futures[f]
            version_data = {}
            try:
                # check for latest version
                version_data.update(f.result())
            except Exception as e:
                try:
                    se = repr(e)
                except Exception as ee:
                    se = f"Bad exception string: {ee}"
                logger.error(
                    "itr % 5d - eta % 5ds: "
                    "Error getting upstream version of %s: %s"
                    % (n_left, eta, node, se),
                )
                version_data["bad"] = "Upstream: Error getting upstream version"
            else:
                logger.info(
                    "itr % 5d - eta % 5ds: %s - %s - %s"
                    % (
                        n_left,
                        eta,
                        node,
                        attrs.get("version", "<no-version>"),
                        version_data["new_version"],
                    ),
                )
            # writing out file
            lzj = LazyJson(f"versions/{node}.json")
            with lzj as attrs:
                attrs.clear()
                attrs.update(version_data)


def update_upstream_versions(
    gx: nx.DiGraph,
    sources: Iterable[AbstractSource] = None,
    debug: bool = False,
    job=1,
    n_jobs=1,
) -> None:
    sources = (
        (
            PyPI(),
            CRAN(),
            NPM(),
            ROSDistro(),
            RawURL(),
            Github(),
            IncrementAlphaRawURL(),
            NVIDIA(),
        )
        if sources is None
        else sources
    )
    updater = (
        _update_upstream_versions_sequential
        if debug
        else _update_upstream_versions_process_pool
    )
    logger.info("Updating upstream versions")
    updater(gx, sources, job=job, n_jobs=n_jobs)


def main(ctx: CliContext, job: int = 1, n_jobs: int = 1) -> None:
    if ctx.debug:
        setup_logger(logger, level="debug")
    else:
        setup_logger(logger)

    logger.info("Reading graph")
    # Graph enabled for inspection
    gx = load_graph()

    # Check if 'versions' folder exists or create a new one;
    os.makedirs("versions", exist_ok=True)
    # call update
    update_upstream_versions(gx, debug=ctx.debug, job=job, n_jobs=n_jobs)
