import collections.abc
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import networkx as nx
import requests

from .all_feedstocks import get_all_feedstocks
from .utils import parse_meta_yaml

logger = logging.getLogger("conda_forge_tick.make_graph")


def get_attrs(name, i):
    sub_graph = {
        "time": time.time(),
        "feedstock_name": name,
        # All feedstocks start out as good
        "bad": False,
    }

    logger.info((i, name))
    r = requests.get(
        "https://raw.githubusercontent.com/"
        "conda-forge/{}-feedstock/master/recipe/"
        "meta.yaml".format(name)
    )
    if r.status_code != 200:
        logger.warn(
            "Something odd happened when fetching recipe "
            "{}: {}".format(name, r.status_code)
        )
        sub_graph["bad"] = "make_graph: {}".format(r.status_code)
        return sub_graph

    text = r.content.decode("utf-8")
    sub_graph["raw_meta_yaml"] = text
    yaml_dict = parse_meta_yaml(text)
    if not yaml_dict:
        logger.warn("Something odd happened when parsing recipe " "{}".format(name))
        sub_graph["bad"] = "make_graph: Could not parse"
        return sub_graph
    sub_graph["meta_yaml"] = yaml_dict
    # TODO: Write schema for dict
    req = yaml_dict.get("requirements", set())
    if req:
        build = list(req.get("build", []) if req.get("build", []) is not None else [])
        host = list(req.get("host", []) if req.get("host", []) is not None else [])
        run = list(req.get("run", []) if req.get("run", []) is not None else [])
        req = build + host + run
        req = set([x.split()[0] for x in req])
    sub_graph["req"] = req

    keys = [("package", "name"), ("package", "version")]
    missing_keys = [k[1] for k in keys if k[1] not in yaml_dict.get(k[0], {})]
    source = yaml_dict.get("source", [])
    if isinstance(source, collections.abc.Mapping):
        source = [source]
    source_keys = set()
    for s in source:
        if not sub_graph.get("url"):
            sub_graph["url"] = s.get("url")
        source_keys |= s.keys()
    if "url" not in source_keys:
        missing_keys.append("url")
    if missing_keys:
        logger.warn("Recipe {} doesn't have a {}".format(name, ", ".join(missing_keys)))
        sub_graph["bad"] = "make_graph: missing {}".format(", ".join(missing_keys))
    for k in keys:
        if k[1] not in missing_keys:
            sub_graph[k[1]] = yaml_dict[k[0]][k[1]]
    k = next(iter((source_keys & hashlib.algorithms_available)), None)
    if k:
        sub_graph["hash_type"] = k
    return sub_graph


def make_graph(names, gx=None):
    logger.info("reading graph")

    if gx is None:
        gx = nx.DiGraph()

    new_names = [name for name in names if name not in gx.nodes]
    old_names = [name for name in names if name in gx.nodes]
    old_names = sorted(old_names, key=lambda n: gx.nodes[n]["time"])

    total_names = new_names + old_names
    logger.info("start loop")

    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(get_attrs(name, i)): name for i, name in enumerate(total_names)}

        for f in as_completed(futures):
            name = futures[f]
            try:
                name, sub_graph = f.result()
            except Exception as e:
                logger.warn("Error adding {} to the graph: {}".format(name, e))
            else:
                if name in new_names:
                    gx.add_node(name, **sub_graph)
                else:
                    gx.nodes[name].update(**sub_graph)

    for node, attrs in gx.node.items():
        for dep in attrs.get("req", []):
            if dep in gx.nodes:
                gx.add_edge(dep, node)
    return gx


def main(args=None):
    logging.basicConfig(level=logging.ERROR)
    logger.setLevel(logging.INFO)
    names = get_all_feedstocks(cached=True)
    gx = nx.read_gpickle("graph.pkl")
    gx = make_graph(names, gx)

    logger.info("writing out file")
    nx.write_gpickle(gx, "graph.pkl")


if __name__ == "__main__":
    main()
