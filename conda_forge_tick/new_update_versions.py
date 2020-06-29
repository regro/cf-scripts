import networkx as nx
import logging
import random
import json
import os
import tqdm

from .utils import setup_logger, load_graph
from .update_sources import (
    AbstractSource,
    PyPI,
    CRAN,
    NPM,
    ROSDistro,
    RawURL,
    Github,
)
from typing import (
    Any,
    Optional,
    Iterable,
    Set,
    Iterator,
    List,
    Dict,
)

# conda_forge_tick :: cft
logger = logging.getLogger("conda-forge-tick._update_versions")


def get_latest_version(
    name: str, payload_meta_yaml: Any, sources: Iterable[AbstractSource],
) -> dict:
    version_data = {}
    with payload_meta_yaml as meta_yaml:
        for source in sources:
            logger.debug("source: %s", source.__class__.__name__)
            url = source.get_url(meta_yaml)
            logger.debug("url: %s", url)
            if url is None:
                continue
            ver = source.get_version(url)
            logger.debug("ver: %s", ver)
            if ver:
                version_data["new_version"] = ver
                return version_data
            else:
                logger.debug(f"Upstream: Could not find version on {source.name}")
                version_data[
                    "bad"
                ] = f"Upstream: Could not find version on {source.name}"
        if not meta_yaml.get("bad"):
            logger.debug("Upstream: unknown source")
            version_data["bad"] = "Upstream: unknown source"

        version_data["new_version"] = False
        return version_data


# It's expected that your environment provide this info.
CONDA_FORGE_TICK_DEBUG = os.environ.get("CONDA_FORGE_TICK_DEBUG", False)


def _update_upstream_versions_sequential(
    gx: nx.DiGraph, sources: Iterable[AbstractSource] = None,
) -> None:
    sources = (
        (PyPI(), CRAN(), NPM(), ROSDistro(), RawURL(), Github())
        if sources is None
        else sources
    )

    _all_nodes = [t for t in gx.nodes.items()]
    random.shuffle(_all_nodes)

    # Inspection the graph object and node update:
    # print(f"Number of nodes: {len(gx.nodes)}")
    node_count = 0
    to_update = []
    for node, node_attrs in tqdm.tqdm(_all_nodes):
        with node_attrs["payload"] as attrs:
            if attrs.get("bad") or attrs.get("archived"):
                continue
            to_update.append((node, attrs))

    for node, node_attrs in to_update:
        # checking each node
        with node_attrs as attrs:
            version_data = {}

            # avoid
            if node == "ca-policy-lcg":
                version_data["new_version"] = False
                node_count += 1
                continue

            # New version request
            try:
                # check for latest version
                version_data.update(get_latest_version(node, attrs, sources))
            except Exception as e:
                try:
                    se = repr(e)
                except Exception as ee:
                    se = f"Bad exception string: {ee}"
                logger.warning(
                    f"Warning: Error getting upstream version of {node}: {se}",
                )
                version_data["bad"] = "Upstream: Error getting upstream version"
            else:
                logger.info(
                    f"# {node_count:<5} - {node} - {attrs.get('version')} - {version_data.get('new_version')}",
                )

            logger.debug("writing out file")
            with open(f"versions/{node}.json", "w") as outfile:
                json.dump(version_data, outfile)
            node_count += 1


def main(args: Any = None) -> None:
    if CONDA_FORGE_TICK_DEBUG:
        setup_logger(logger, level="debug")
    else:
        setup_logger(logger)

    logger.info("Reading graph")
    # Graph enabled for inspection
    gx = load_graph()

    # Check if 'versions' folder exists or create a new one;
    os.makedirs("versions", exist_ok=True)
    # call update
    _update_upstream_versions_sequential(gx)


if __name__ == "__main__":
    main()
