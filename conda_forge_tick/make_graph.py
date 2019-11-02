import re
import collections.abc
import hashlib
import logging
import os
import time
import random
import builtins
from copy import deepcopy

import github3
import networkx as nx
import requests
import yaml

from xonsh.lib.collections import ChainDB, _convert_to_dict

from conda_forge_tick.utils import github_client, load
from .all_feedstocks import get_all_feedstocks
from .utils import (
    parse_meta_yaml,
    setup_logger,
    get_requirements,
    executor,
    load_graph,
    dump_graph,
    LazyJson,
)
from .git_utils import refresh_pr, is_github_api_limit_reached, close_out_labels

logger = logging.getLogger("conda_forge_tick.make_graph")
pin_sep_pat = re.compile(" |>|<|=|\[")

NUM_GITHUB_THREADS = 4


def fetch_file(filepath, name):
    """Fetch fil from github

    Parameters
    ----------
    filepath : str
        The path to the specific file
    name : str
        The name of the feedstock

    Returns
    -------
    text : str
        The raw text
    failed : False or str
        False if it passed or the status code if failed
    """
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
        failed = r.status_code

    text = r.content.decode("utf-8")
    return text, failed


# TODO: should we pass in lazy json maybe as a dict-like?
def make_node_attributes_from_texts(
    node_attrs, name, raw_meta_yaml_text, raw_cf_yaml_text=None
):
    """Make a node with attributes from loaded (but not parsed) text

    Parameters
    ----------
    node_attrs : MutableMap
        A dict like used to store the data
    name : str
        The feedstock name
    raw_meta_yaml_text : str
        The meta.yaml text
    raw_cf_yaml_text : str
        The text from the conda-forge.yaml file

    Returns
    -------
    node_attrs : dict
        The dict representing the node attributes
    """
    node_attrs.update(
        {
            "feedstock_name": name,
            # All feedstocks start out as good, they could become
            # bad by having bad links or other unloadable reasons
            "bad": False,
        }
    )

    node_attrs["raw_meta_yaml"] = raw_meta_yaml_text

    # parse the meta yaml text with all the architectures
    # TODO: include conda_build_config.yaml for parsing
    # TODO: handle arch differences, make arch specific requirements entries
    # TODO: merge values that can be merged while preserving order
    yaml_dict = ChainDB(
        *[
            parse_meta_yaml(raw_meta_yaml_text, platform=plat)
            for plat in ["win", "osx", "linux"]
        ]
    )

    # If we couldn't parse bounce out
    if not yaml_dict:
        logger.warn("Something odd happened when parsing recipe " "{}".format(name))
        node_attrs["bad"] = "make_graph: Could not parse"
        return node_attrs

    node_attrs["meta_yaml"] = _convert_to_dict(yaml_dict)

    # handle multi outputs, get the names so we can make the lookup table
    if "outputs" in yaml_dict:
        node_attrs["outputs_names"] = sorted(
            list(set(d.get("name", "") for d in yaml_dict["outputs"]))
        )

    # TODO: Write schema for dict
    req = get_requirements(yaml_dict)
    node_attrs["req"] = req

    keys = [("package", "name"), ("package", "version")]
    missing_keys = [k[1] for k in keys if k[1] not in yaml_dict.get(k[0], {})]

    source = yaml_dict.get("source", [])
    if isinstance(source, collections.abc.Mapping):
        source = [source]
    source_keys = set()
    for s in source:
        if not node_attrs.get("url"):
            node_attrs["url"] = s.get("url")
        source_keys |= s.keys()
    if "url" not in source_keys:
        missing_keys.append("url")

    if missing_keys:
        logger.warn("Recipe {} doesn't have a {}".format(name, ", ".join(missing_keys)))
    for k in keys:
        if k[1] not in missing_keys:
            node_attrs[k[1]] = yaml_dict[k[0]][k[1]]

    # extract the hash type if available
    k = sorted(source_keys & hashlib.algorithms_available, reverse=True)
    if k:
        node_attrs["hash_type"] = k[0]

    # if the conda-forge.yaml is none drop out
    if raw_cf_yaml_text is None:
        return node_attrs
    node_attrs["conda-forge.yml"] = {
        k: v
        for k, v in yaml.safe_load(raw_cf_yaml_text).items()
        if k in {"provider", "max_py_ver", "max_r_ver", "compiler_stack"}
    }
    return node_attrs


def get_attrs(name, i):
    logger.info((i, name))
    # read up the file from the web, replace this for local run

    # parse
    lzj = LazyJson(f"node_attrs/{name}.json")
    with lzj as sub_graph:
        text, failed = fetch_file("recipe/meta.yaml", name)
        if failed:
            sub_graph.update({"bad": f"make_graph: {failed}"})
            return sub_graph
        cf_yaml_text, failed = fetch_file("conda-forge.yml", name)
        cf_yaml_text = cf_yaml_text if not failed else None
        make_node_attributes_from_texts(sub_graph, name, text, cf_yaml_text)
    return lzj


def _build_graph_process_pool(gx, names, new_names):
    with executor("dask", max_workers=20) as (pool, as_completed):
        futures = {
            pool.submit(get_attrs, name, i): name for i, name in enumerate(names)
        }

        for f in as_completed(futures):
            name = futures[f]
            try:
                sub_graph = {"payload": f.result()}
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
            sub_graph = {"payload": get_attrs(name, i)}
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

    # make the outputs look up table so we can link properly
    outputs_lut = {
        k: node_name
        for node_name, node in gx.nodes.items()
        for k in node.get("payload", {}).get("outputs_names", [])
    }
    for node, node_attrs in gx2.nodes.items():
        with node_attrs["payload"] as attrs:
            for dep in attrs.get("req", []):
                if dep in outputs_lut:
                    gx.add_edge(outputs_lut[dep], node)
                    continue
                elif dep not in gx.nodes:
                    # for packages which aren't feedstocks (outputs!)
                    lzj = LazyJson(f"node_attrs/{dep}.json")
                    lzj.update(feedstock_name=dep, bad=False)
                    gx.add_node(dep, payload=lzj)
                gx.add_edge(dep, node)
    logger.info("new nodes and edges infered")
    return gx


def update_graph_pr_status(gx: nx.DiGraph) -> nx.DiGraph:
    failed_refresh = 0
    succeeded_refresh = 0
    gh = github_client()
    futures = {}
    node_ids = list(gx.nodes)
    # this makes sure that github rate limits are dispersed
    random.shuffle(node_ids)
    with executor("thread", NUM_GITHUB_THREADS) as (pool, as_completed):
        for node_id in node_ids:
            node = gx.nodes[node_id]["payload"]
            prs = node.get("PRed", [])
            for i, migration in enumerate(prs):
                pr_json = migration.get("PR", None)
                # allow for false
                if pr_json:
                    future = pool.submit(refresh_pr, pr_json, gh)
                    futures[future] = (node_id, i)

        for f in as_completed(futures):
            name, i = futures[f]
            try:
                res = f.result()
                if res:
                    succeeded_refresh += 1
                    with gx.nodes[name]["payload"] as node:
                        node["PRed"][i]["PR"].update(**res)
                    logger.info("Updated json for {}: {}".format(name, res["id"]))
            except github3.GitHubError as e:
                logger.critical("GITHUB ERROR ON FEEDSTOCK: {}".format(name))
                failed_refresh += 1
                if is_github_api_limit_reached(e, gh):
                    break
            except github3.exceptions.ConnectionError as e:
                logger.critical("GITHUB ERROR ON FEEDSTOCK: {}".format(name))
                failed_refresh += 1
            except Exception as e:
                logger.critical(
                    "ERROR ON FEEDSTOCK: {}: {}".format(
                        name, gx.nodes[name]["payload"]["PRed"][i]["data"]
                    )
                )
                raise
    logger.info("JSON Refresh failed for {} PRs".format(failed_refresh))
    logger.info("JSON Refresh succeed for {} PRs".format(succeeded_refresh))
    return gx


def close_labels(gx: nx.DiGraph) -> nx.DiGraph:
    failed_refresh = 0
    succeeded_refresh = 0
    gh = github_client()
    futures = {}
    node_ids = list(gx.nodes)
    # this makes sure that github rate limits are dispersed
    random.shuffle(node_ids)
    with executor("thread", NUM_GITHUB_THREADS) as (pool, as_completed):
        for node_id in node_ids:
            node = gx.nodes[node_id]["payload"]
            prs = node.get("PRed", [])
            for i, migration in enumerate(prs):
                pr_json = migration.get("PR", None)
                # allow for false
                if pr_json:
                    future = pool.submit(close_out_labels, pr_json, gh)
                    futures[future] = (node_id, i)

        for f in as_completed(futures):
            name, i = futures[f]
            try:
                res = f.result()
                if res:
                    succeeded_refresh += 1
                    # add a piece of metadata which makes the muid matchup
                    # fail
                    with gx.nodes[name]["payload"] as node:
                        node["PRed"][i]["data"]["bot_rerun"] = time.time()
                        if (
                            "bot_rerun"
                            not in gx.nodes[name]["payload"]["PRed"][i]["keys"]
                        ):
                            node["PRed"][i]["keys"].append("bot_rerun")
                    logger.info(
                        "Closed and removed PR and branch for "
                        "{}: {}".format(name, res["id"])
                    )
            except github3.GitHubError as e:
                logger.critical("GITHUB ERROR ON FEEDSTOCK: {}".format(name))
                failed_refresh += 1
                if is_github_api_limit_reached(e, gh):
                    break
            except Exception as e:
                logger.critical(
                    "ERROR ON FEEDSTOCK: {}: {}".format(
                        name, gx.nodes[name]["payload"]["PRed"][i]["data"]
                    )
                )
                raise
    logger.info("bot re-run failed for {} PRs".format(failed_refresh))
    logger.info("bot re-run succeed for {} PRs".format(succeeded_refresh))
    return gx


def main(args=None):
    setup_logger(logger)
    names = get_all_feedstocks(cached=True)
    if os.path.exists("graph.json"):
        gx = load_graph()
    else:
        gx = None
    gx = make_graph(names, gx)
    print([k for k, v in gx.nodes.items() if "payload" not in v])
    # Utility flag for testing -- we don't need to always update GH
    no_github_fetch = os.environ.get("CONDA_FORGE_TICK_NO_GITHUB_REQUESTS")
    if not no_github_fetch:
        gx = close_labels(gx)
        gx = update_graph_pr_status(gx)

    logger.info("writing out file")
    dump_graph(gx)


if __name__ == "__main__":
    main()
