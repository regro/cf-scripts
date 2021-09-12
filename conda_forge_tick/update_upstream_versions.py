import networkx as nx
import logging
import random
import json
import time
import os
import tqdm
from concurrent.futures import as_completed

from .utils import setup_logger, load_graph, executor
from .update_sources import (
    AbstractSource,
    PyPI,
    CRAN,
    NPM,
    ROSDistro,
    RawURL,
    Github,
    IncrementAlphaRawURL,
)
from typing import Any, Iterable

# conda_forge_tick :: cft
logger = logging.getLogger("conda_forge_tick.update_upstream_versions")


def get_latest_version(
    name: str,
    meta_yaml: Any,
    sources: Iterable[AbstractSource],
) -> dict:
    version_data = {"new_version": False}

    # avoid this one since it runs too long and hangs the bot
    if name == "ca-policy-lcg":
        return version_data

    excs = []
    for source in sources:
        try:
            logger.debug("source: %s", source.__class__.__name__)
            url = source.get_url(meta_yaml)
            logger.debug("url: %s", url)
            if url is None:
                continue
            ver = source.get_version(url, meta_yaml)
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

    return version_data


def _update_upstream_versions_sequential(
    gx: nx.DiGraph,
    sources: Iterable[AbstractSource] = None,
) -> None:

    _all_nodes = [t for t in gx.nodes.items()]
    random.shuffle(_all_nodes)

    # Inspection the graph object and node update:
    # print(f"Number of nodes: {len(gx.nodes)}")
    node_count = 0
    to_update = []
    for node, node_attrs in _all_nodes:
        attrs = node_attrs["payload"]
        if (attrs.get("bad") and "Upstream" not in attrs.get("bad")) or attrs.get(
            "archived",
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
        with open(f"versions/{node}.json", "w") as outfile:
            json.dump(version_data, outfile)
        node_count += 1


def _update_upstream_versions_process_pool(
    gx: nx.DiGraph,
    sources: Iterable[AbstractSource],
) -> None:
    futures = {}
    # this has to be threads because the url hashing code uses a Pipe which
    # cannot be spawned from a process
    with executor(kind="dask", max_workers=5) as pool:
        _all_nodes = [t for t in gx.nodes.items()]
        random.shuffle(_all_nodes)

        for node, node_attrs in tqdm.tqdm(_all_nodes):
            attrs = node_attrs["payload"]
            if (attrs.get("bad") and "Upstream" not in attrs["bad"]) or attrs.get(
                "archived",
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
            with open(f"versions/{node}.json", "w") as outfile:
                json.dump(version_data, outfile)


def update_upstream_versions(
    gx: nx.DiGraph,
    sources: Iterable[AbstractSource] = None,
    debug: bool = False,
) -> None:
    sources = (
        (PyPI(), CRAN(), NPM(), ROSDistro(), RawURL(), Github(), IncrementAlphaRawURL())
        if sources is None
        else sources
    )
    updater = (
        _update_upstream_versions_sequential
        if debug
        else _update_upstream_versions_process_pool
    )
    logger.info("Updating upstream versions")
    updater(gx, sources)


def main(args: Any = None) -> None:
    if args.debug:
        setup_logger(logger, level="debug")
    else:
        setup_logger(logger)

    logger.info("Reading graph")
    # Graph enabled for inspection
    gx = load_graph()

    # Check if 'versions' folder exists or create a new one;
    os.makedirs("versions", exist_ok=True)
    # call update
    update_upstream_versions(gx, debug=args.debug)


if __name__ == "__main__":
    main()
