import re
import collections.abc
import datetime
import hashlib
import logging
import os
import time
import random
import builtins
import contextlib
from copy import deepcopy

import github3
import networkx as nx
import requests
import yaml

from xonsh.lib.collections import ChainDB, _convert_to_dict
from .all_feedstocks import get_all_feedstocks
from .utils import parse_meta_yaml, setup_logger, get_requirements, executor
from .git_utils import refresh_pr, is_github_api_limit_reached, close_out_labels

logger = logging.getLogger("conda_forge_tick.make_graph")
pin_sep_pat = re.compile(" |>|<|=|\[")


NUM_GITHUB_THREADS = 4


def get_attrs(name, i):
    sub_graph = {
        "time": time.time(),
        "feedstock_name": name,
        # All feedstocks start out as good
        "bad": False,
    }

    logger.info((i, name))
    def fetch_file(filepath):
        r = requests.get(
            "https://raw.githubusercontent.com/"
            "conda-forge/{}-feedstock/master/{}".format(name, filepath)
        )
        failed = False
        if r.status_code != 200:
            logger.warn(
                "Something odd happened when fetching recipe "
                "{}: {}".format(name, r.status_code)
            )
            sub_graph["bad"] = "make_graph: {}".format(r.status_code)
            failed = True

        text = r.content.decode("utf-8")
        return text, failed

    text, failed = fetch_file('recipe/meta.yaml')
    if failed:
        return sub_graph
    sub_graph["raw_meta_yaml"] = text
    yaml_dict = ChainDB(
        *[parse_meta_yaml(text, platform=plat) for plat in ["win", "osx", "linux"]]
    )
    if not yaml_dict:
        logger.warn("Something odd happened when parsing recipe " "{}".format(name))
        sub_graph["bad"] = "make_graph: Could not parse"
        return sub_graph
    sub_graph["meta_yaml"] = _convert_to_dict(yaml_dict)

    # Get the conda-forge.yml
    text, failed = fetch_file('conda-forge.yml')
    if failed:
        return sub_graph
    sub_graph["conda-forge.yml"] = {k: v for k, v in  yaml.safe_load(text).items() if
        k in {'provider', 'max_py_ver', 'max_r_ver', 'compiler_stack'}}

    # TODO: Write schema for dict
    req = get_requirements(yaml_dict)
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
    for k in keys:
        if k[1] not in missing_keys:
            sub_graph[k[1]] = yaml_dict[k[0]][k[1]]
    k = next(iter((source_keys & hashlib.algorithms_available)), None)
    if k:
        sub_graph["hash_type"] = k
    return sub_graph


def _build_graph_process_pool(gx, names, new_names):
    with executor('dask', max_workers=20) as (pool, as_completed):
        futures = {
            pool.submit(get_attrs, name, i): name for i, name in enumerate(names)
        }

        for f in as_completed(futures):
            name = futures[f]
            try:
                sub_graph = f.result()
            except Exception as e:
                logger.warn("Error adding {} to the graph: {}".format(name, e))
            else:
                if name in new_names:
                    gx.add_node(name, **sub_graph)
                else:
                    gx.nodes[name].update(**sub_graph)


def _build_graph_sequential(gx, names, new_names):
    for i, name in enumerate(names):
        try:
            sub_graph = get_attrs(name, i)
        except Exception as e:
            logger.warn("Error adding {} to the graph: {}".format(name, e))
        else:
            if name in new_names:
                gx.add_node(name, **sub_graph)
            else:
                gx.nodes[name].update(**sub_graph)


def make_graph(names, gx=None):
    logger.info("reading graph")

    if gx is None:
        gx = nx.DiGraph()

    new_names = [name for name in names if name not in gx.nodes]
    old_names = [name for name in names if name in gx.nodes]
    old_names = sorted(old_names, key=lambda n: gx.nodes[n].get("time", 0))

    total_names = new_names + old_names
    logger.info("start loop")
    env = builtins.__xonsh__.env
    debug = env.get("CONDA_FORGE_TICK_DEBUG", False)
    builder = _build_graph_sequential if debug else _build_graph_process_pool
    builder(gx, total_names, new_names)
    logger.info("loop completed")

    gx2 = deepcopy(gx)
    logger.info("inferring nodes and edges")
    for node, attrs in gx2.node.items():
        for dep in attrs.get("req", []):
            if dep not in gx.nodes:
                gx.add_node(dep, archived=True, time=time.time())
            gx.add_edge(dep, node)
    logger.info("new nodes and edges infered")
    return gx


def github_client():
    if os.environ.get('GITHUB_TOKEN'):
        return github3.login(token=os.environ['GITHUB_TOKEN'])
    else:
        return  github3.login(os.environ["USERNAME"], os.environ["PASSWORD"])


def update_graph_pr_status(gx: nx.DiGraph) -> nx.DiGraph:
    gh = github_client()
    futures = {}
    node_ids = list(gx.nodes)
    # this makes sure that github rate limits are dispersed
    random.shuffle(node_ids)
    with executor('thread', NUM_GITHUB_THREADS) as (pool, as_completed):
        for node_id in node_ids:
            node = gx.nodes[node_id]
            prs = node.get("PRed_json", {})
            for migrator, pr_json in prs.items():
                # allow for false
                if pr_json:
                    future = pool.submit(refresh_pr, pr_json, gh)
                    futures[future] = (node_id, migrator)

        for f in as_completed(futures):
            name, muid = futures[f]
            try:
                res = f.result()
                if res:
                    gx.nodes[name]["PRed_json"][muid].update(**res)
                    logger.info("Updated json for {}: {}".format(name, res["id"]))
            except github3.GitHubError as e:
                logger.critical("GITHUB ERROR ON FEEDSTOCK: {}".format(name))
                if is_github_api_limit_reached(e, gh):
                    break
            except Exception as e:
                logger.critical("ERROR ON FEEDSTOCK: {}: {}".format(name, muid))
                raise
    return gx


def close_labels(gx: nx.DiGraph) -> nx.DiGraph:
    gh = github_client()
    futures = {}
    node_ids = list(gx.nodes)
    # this makes sure that github rate limits are dispersed
    random.shuffle(node_ids)
    with executor('thread', NUM_GITHUB_THREADS) as (pool, as_completed):
        for node_id in node_ids:
            node = gx.nodes[node_id]
            prs = node.get("PRed_json", {})
            for migrator, pr_json in prs.items():
                # allow for false
                if pr_json:
                    future = pool.submit(close_out_labels, pr_json, gh)
                    futures[future] = (node_id, migrator)

        for f in as_completed(futures):
            name, muid = futures[f]
            try:
                res = f.result()
                if res:
                    gx.node[name]["PRed"].remove(muid)
                    del gx.nodes[name]["PRed_json"][muid]
                    logger.info(
                        "Closed and removed PR and branch for "
                        "{}: {}".format(name, res["id"])
                    )
            except github3.GitHubError as e:
                logger.critical("GITHUB ERROR ON FEEDSTOCK: {}".format(name))
                if is_github_api_limit_reached(e, gh):
                    break
            except Exception as e:
                logger.critical("ERROR ON FEEDSTOCK: {}: {}".format(name, muid))
                raise
    return gx


def main(args=None):
    setup_logger(logger)
    names = get_all_feedstocks(cached=True)
    if os.path.exists("graph.pkl"):
        gx = nx.read_gpickle("graph.pkl")
    else:
        gx = None
    gx = make_graph(names, gx)
    # Utility flag for testing -- we don't need to always update GH
    no_github_fetch = os.environ.get('CONDA_FORGE_TICK_NO_GITHUB_REQUESTS')
    if not no_github_fetch:
        gx = update_graph_pr_status(gx)
        gx = close_labels(gx)

    logger.info("writing out file")
    nx.write_gpickle(gx, "graph.pkl")


if __name__ == "__main__":
    main()
