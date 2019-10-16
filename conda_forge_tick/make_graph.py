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
from .utils import parse_meta_yaml, setup_logger, get_requirements, executor, \
    load_graph, dump_graph, LazyJson
from .git_utils import refresh_pr, is_github_api_limit_reached, close_out_labels

logger = logging.getLogger("conda_forge_tick.make_graph")
pin_sep_pat = re.compile(" |>|<|=|\[")


NUM_GITHUB_THREADS = 4


def get_attrs(name, i):
    lzj = LazyJson(f'node_attrs/{name}.json')
    with lzj as sub_graph:
        sub_graph.update({
            "feedstock_name": name,
            # All feedstocks start out as good
            "bad": False,
        })

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

        # handle multi outputs
        if 'outputs' in yaml_dict:
            sub_graph['outputs_names'] = list(set([d.get('name', '') for d in yaml_dict['outputs']))

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
        k = sorted(source_keys & hashlib.algorithms_available, reverse=True)
        if k:
            sub_graph["hash_type"] = k[0]
    return lzj


def _build_graph_process_pool(gx, names, new_names):
    with executor('dask', max_workers=20) as (pool, as_completed):
        futures = {
            pool.submit(get_attrs, name, i): name for i, name in enumerate(names)
        }

        for f in as_completed(futures):
            name = futures[f]
            try:
                sub_graph = {'payload': f.result()}
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
            sub_graph = {'payload': get_attrs(name, i)}
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
    outputs_lut = {k: node_name for k in node.get('payload', {}).get('outputs_names', []) for node_name, node in gx.nodes.items()}
    for node, node_attrs in gx2.node.items():
        with node_attrs['payload'] as attrs:
            for dep in attrs.get("req", []):
                if dep in outputs_lut:
                    gx.add_edge(outputs_lut[dep], node)
                    continue
                elif dep not in gx.nodes:
                    # for packages which aren't feedstocks (outputs!)
                    lzj = LazyJson(f'node_attrs/{dep}.json')
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
    with executor('thread', NUM_GITHUB_THREADS) as (pool, as_completed):
        for node_id in node_ids:
            node = gx.nodes[node_id]['payload']
            prs = node.get("PRed", [])
            for i, migration in enumerate(prs):
                pr_json = migration.get('PR', None)
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
                    with gx.node[name]['payload'] as node:
                        node["PRed"][i]['PR'].update(**res)
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
                logger.critical("ERROR ON FEEDSTOCK: {}: {}".format(
                    name,
                    gx.nodes[name]['payload']["PRed"][i]['data']))
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
    with executor('thread', NUM_GITHUB_THREADS) as (pool, as_completed):
        for node_id in node_ids:
            node = gx.nodes[node_id]['payload']
            prs = node.get("PRed", [])
            for i, migration in enumerate(prs):
                pr_json = migration.get('PR', None)
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
                    with gx.node[name]['payload'] as node:
                        node['PRed'][i]['data']['bot_rerun'] = time.time()
                        if 'bot_rerun' not in gx.node[name]['payload']["PRed"][i]['keys']:
                            node['PRed'][i]['keys'].append('bot_rerun')
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
                logger.critical("ERROR ON FEEDSTOCK: {}: {}".format(
                    name, gx.nodes[name]['payload']["PRed"][i]['data']))
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
    print([k for k, v in gx.nodes.items() if 'payload' not in v])
    # Utility flag for testing -- we don't need to always update GH
    no_github_fetch = os.environ.get('CONDA_FORGE_TICK_NO_GITHUB_REQUESTS')
    if not no_github_fetch:
        gx = close_labels(gx)
        gx = update_graph_pr_status(gx)

    logger.info("writing out file")
    dump_graph(gx)


if __name__ == "__main__":
    main()
