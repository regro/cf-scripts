import networkx as nx
import logging
import random
import json
import os
import tqdm

from utils import setup_logger, load_graph
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
logger = logging.getLogger("conda-forge-tick._update_versions")


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
                meta["bad"] = f"Upstream: Could not find version on {source.name}"
        if not meta_yaml.get("bad"):
            logger.debug("Upstream: unknown source")
            meta["bad"] = "Upstream: unknown source"
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

    to_update = []
    for node, node_attrs in tqdm.tqdm(_all_nodes):
        attrs = node_attrs["payload"]
        if attrs.get("bad") or attrs.get("archived"):
            attrs["new_version"] = False
            continue
        to_update.append((node, attrs))

    up_to = {}
    for node, node_attrs in to_update:
        # checking each node
        with node_attrs as attrs:
            up_to = {}

            # verify the actual situation of the package;
            actual_ver = str(attrs.get("version"))

            # rude exception
            if node == "ca-policy-lcg":
                up_to["ca-policy-lcg"] = {
                    "bad": attrs.get("bad"),
                    "new_version": False,
                    "new_version_attempts": attrs.get("new_version_attempts"),
                    "new_version_errors": attrs.get("new_version_errors")
                }
                Node_count += 1
                continue

            # New verison request
            try:
                new_version = get_latest_version(node, attrs, sources)
                attrs["new_version"] = new_version or attrs["new_version"]
            except Exception as e:
                try:
                    se = repr(e)
                except Exception as ee:
                    se = "Bad exception string: {}".format(ee)
                logger.warning(
                    f"Warning: Error getting upstream version of {node}: {se}"
                )
                attrs["bad"] = "Upstream: Error getting upstream version"
            else:
                logger.info(
                    f"# {Node_count:<5} - {node} - {attrs.get('version')} - {attrs.get('new_version')}",
                )
            up_to[f"{node}"] = {
                "bad": attrs.get("bad"),
                "new_version": attrs.get("new_version"),
                "new_version_attempts": attrs.get("new_version_attempts"),
                "new_version_errors": attrs.get("new_version_errors")
            }
            Node_count += 1
    return up_to


def main(args: Any = None) -> None:
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