import networkx as nx
import logging
import random
import json
import os

from conda_forge_tick.utils import setup_logger, load_graph
from update_sources import (
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
)

# conda_forge_tick :: cft
logger = logging.getLogger("cft._update_versions")


def get_latest_version(
    name: str, payload_meta_yaml: Any, sources: Iterable[AbstractSource]
):
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
                return ver
            else:
                logger.debug(f"Upstream: Could not find version on {source.name}")
        if not meta_yaml.get("bad"):
            logger.debug("Upstream: unknown source")
        return False


# It's expected that your environment provide this info.
CONDA_FORGE_TICK_DEBUG = os.environ.get("CONDA_FORGE_TICK_DEBUG", False)


def new_update_upstream_versions(
    gx: nx.DiGraph, sources: Iterable[AbstractSource] = None
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
    Node_count = 0

    to_update = {}
    to_update["nodes"] = []
    for node, node_attrs in _all_nodes:
        # checking each node
        with node_attrs["payload"] as attrs:
            # rude exception
            if node == "ca-policy-lcg":
                to_update["nodes"].append({"id": str(node), "version": "False"})
                Node_count += 1
                continue

            # verify the actual situation of the package;
            actual_ver = str(attrs.get("version"))
            if attrs.get("bad") or attrs.get("archived"):
                logger.info(
                    f"# {Node_count:<5} - {node:<30} - ver: {actual_ver:<10} - bad/archived"
                )
                Node_count += 1
                continue
            # New verison request
            try:
                new_version = get_latest_version(node, attrs, sources)
            except Exception as e:
                try:
                    se = repr(e)
                except Exception as ee:
                    se = "Bad exception string: {}".format(ee)
                logger.warning(
                    f"Warning: Error getting upstream version of {node}: {se}"
                )

            logger.info(
                f"# {Node_count:<5} - {node:<30} - ver: {actual_ver:<10} - new ver: {new_version}"
            )
            to_update["nodes"].append({"id": str(node), "version": str(new_version)})
            Node_count += 1
    return to_update


def main(args: Any = None) -> None:
    logger.info("cft :: conda_forge_tick")
    if CONDA_FORGE_TICK_DEBUG:
        setup_logger(logger, level="debug")
    else:
        setup_logger(logger)

    logger.info("Reading graph")
    # Graph enabled for inspection
    gx = load_graph()

    # call update
    to_update = new_update_upstream_versions(gx)

    logger.info("writing out file")
    with open("new_version.json", "w") as outfile:
        json.dump(to_update, outfile)


if __name__ == "__main__":
    main()