import re
import collections.abc
import hashlib
import logging
import os
import time
import random
from collections import defaultdict, OrderedDict
from concurrent.futures import as_completed
from copy import deepcopy
import typing
from requests import Response
from typing import List, Optional, Set

import github3
import networkx as nx
import requests
import yaml
import textwrap
import tqdm

from xonsh.lib.collections import ChainDB, _convert_to_dict
from .xonsh_utils import env

from conda_forge_tick.utils import github_client, as_iterable
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
from .git_utils import (
    refresh_pr,
    is_github_api_limit_reached,
    close_out_labels,
)
from .contexts import GithubContext

if typing.TYPE_CHECKING:
    from .cli import CLIArgs
    from .migrators_types import RequirementsTypedDict, TestTypedDict

logger = logging.getLogger("conda_forge_tick.make_graph")
pin_sep_pat = re.compile(r" |>|<|=|\[")


NUM_GITHUB_THREADS = 2

github_username = env.get("USERNAME", "")
github_password = env.get("PASSWORD", "")
github_token = env.get("GITHUB_TOKEN")

ghctx = GithubContext(
    github_username=github_username,
    github_password=github_password,
    github_token=github_token,
    circle_build_url=os.getenv("CIRCLE_BUILD_URL", ""),
)


def _fetch_file(name: str, filepath: str) -> typing.Union[str, Response]:
    r = requests.get(
        "https://raw.githubusercontent.com/"
        "conda-forge/{}-feedstock/master/{}".format(name, filepath),
    )
    if r.status_code != 200:
        logger.error(
            f"Something odd happened when fetching recipe {name}: {r.status_code}",
        )
        return r

    text = r.content.decode("utf-8")
    return text


# TODO: include other files like build_sh
def populate_feedstock_attributes(
    name: str,
    sub_graph: LazyJson,
    meta_yaml: typing.Union[str, Response] = "",
    conda_forge_yaml: typing.Union[str, Response] = "",
    # build_sh: typing.Union[str, Response] = "",
    # pre_unlink: typing.Union[str, Response] = "",
    # post_link: typing.Union[str, Response] = "",
    # pre_link: typing.Union[str, Response] = "",
    # activate: typing.Union[str, Response] = "",
) -> LazyJson:
    """Parse the various configuration information into something usable

    Notes
    -----
    If the return is bad hand the response itself in so that it can be parsed
    for meaning.
    """
    sub_graph.update({"feedstock_name": name, "bad": False})
    # handle all the raw strings
    if isinstance(meta_yaml, Response):
        sub_graph["bad"] = f"make_graph: {meta_yaml.status_code}"
        return sub_graph
    sub_graph["raw_meta_yaml"] = meta_yaml

    # Get the conda-forge.yml
    if isinstance(conda_forge_yaml, str):
        sub_graph["conda-forge.yml"] = {
            k: v
            for k, v in yaml.safe_load(conda_forge_yaml).items()
            if k
            in {
                "provider",
                "min_r_ver",
                "min_py_ver",
                "max_py_ver",
                "max_r_ver",
                "compiler_stack",
                "bot",
            }
        }

    yaml_dict = ChainDB(
        *[parse_meta_yaml(meta_yaml, platform=plat) for plat in ["win", "osx", "linux"]]
    )
    if not yaml_dict:
        logger.error(f"Something odd happened when parsing recipe {name}")
        sub_graph["bad"] = "make_graph: Could not parse"
        return sub_graph
    sub_graph["meta_yaml"] = _convert_to_dict(yaml_dict)
    meta_yaml = sub_graph["meta_yaml"]

    sub_graph["strong_exports"] = False
    # TODO: make certain to remove None
    requirements_dict = defaultdict(set)
    for block in [meta_yaml] + meta_yaml.get("outputs", []) or []:
        req: "RequirementsTypedDict" = block.get("requirements", {}) or {}
        if isinstance(req, list):
            requirements_dict["run"].update(set(req))
            continue
        for section in ["build", "host", "run"]:
            requirements_dict[section].update(
                list(as_iterable(req.get(section, []) or []))
            )
        test: "TestTypedDict" = block.get("test", {})
        requirements_dict["test"].update(test.get("requirements", []) or [])
        requirements_dict["test"].update(test.get("requires", []) or [])
        run_exports = (block.get("build", {}) or {}).get("run_exports", {})
        if isinstance(run_exports, dict) and run_exports.get("strong"):
            sub_graph["strong_exports"] = True
    for k in list(requirements_dict.keys()):
        requirements_dict[k] = set(v for v in requirements_dict[k] if v)

    sub_graph["total_requirements"] = dict(requirements_dict)
    sub_graph["requirements"] = {
        k: {pin_sep_pat.split(x)[0].lower() for x in v}
        for k, v in sub_graph["total_requirements"].items()
    }

    # handle multi outputs
    if "outputs" in yaml_dict:
        sub_graph["outputs_names"] = sorted(
            list({d.get("name", "") for d in yaml_dict["outputs"]}),
        )

    # TODO: Write schema for dict
    # TODO: remove this
    req = get_requirements(yaml_dict)
    sub_graph["req"] = req

    keys = [("package", "name"), ("package", "version")]
    missing_keys = [k[1] for k in keys if k[1] not in yaml_dict.get(k[0], {})]
    source = yaml_dict.get("source", [])
    if isinstance(source, collections.abc.Mapping):
        source = [source]
    source_keys: Set[str] = set()
    for s in source:
        if not sub_graph.get("url"):
            sub_graph["url"] = s.get("url")
        source_keys |= s.keys()
    if "url" not in source_keys:
        missing_keys.append("url")
    if missing_keys:
        logger.error(f"Recipe {name} doesn't have a {', '.join(missing_keys)}")
    for k in keys:
        if k[1] not in missing_keys:
            sub_graph[k[1]] = yaml_dict[k[0]][k[1]]
    kl = list(sorted(source_keys & hashlib.algorithms_available, reverse=True))
    if kl:
        sub_graph["hash_type"] = kl[0]
    return sub_graph


def get_attrs(name: str, i: int) -> LazyJson:
    # These fetches could be done via async/multiprocessing
    meta_yaml = _fetch_file(name, "recipe/meta.yaml")
    conda_forge_yaml = _fetch_file(name, "conda-forge.yml")

    lzj = LazyJson(f"node_attrs/{name}.json")
    with lzj as sub_graph:
        populate_feedstock_attributes(
            name, sub_graph, meta_yaml=meta_yaml, conda_forge_yaml=conda_forge_yaml,
        )
    return lzj


def _build_graph_process_pool(
    gx: nx.DiGraph, names: List[str], new_names: List[str],
) -> None:
    with executor("thread", max_workers=20) as pool:
        futures = {
            pool.submit(get_attrs, name, i): name for i, name in enumerate(names)
        }
        logger.info("submitted all nodes")

        n_tot = len(futures)
        n_left = len(futures)
        start = time.time()
        eta = -1
        for f in as_completed(futures):
            n_left -= 1
            if n_left % 10 == 0:
                eta = (time.time() - start) / (n_tot - n_left) * n_left
            name = futures[f]
            try:
                sub_graph = {"payload": f.result()}
                logger.info("itr % 5d - eta % 5ds: finished %s", n_left, eta, name)
            except Exception as e:
                logger.error(
                    "itr % 5d - eta % 5ds: Error adding %s to the graph: %s",
                    n_left,
                    eta,
                    name,
                    repr(e),
                )
            else:
                if name in new_names:
                    gx.add_node(name, **sub_graph)
                else:
                    gx.nodes[name].update(**sub_graph)


def _build_graph_sequential(
    gx: nx.DiGraph, names: List[str], new_names: List[str],
) -> None:
    for i, name in enumerate(names):
        try:
            sub_graph = {"payload": get_attrs(name, i)}
        except Exception as e:
            logger.error(f"Error adding {name} to the graph: {e}")
        else:
            if name in new_names:
                gx.add_node(name, **sub_graph)
            else:
                gx.nodes[name].update(**sub_graph)


def make_graph(names: List[str], gx: Optional[nx.DiGraph] = None) -> nx.DiGraph:
    logger.info("reading graph")

    if gx is None:
        gx = nx.DiGraph()

    new_names = [name for name in names if name not in gx.nodes]
    old_names = [name for name in names if name in gx.nodes]
    # silly typing force
    assert gx is not None
    old_names = sorted(  # type: ignore
        old_names, key=lambda n: gx.nodes[n].get("time", 0)
    )  # type: ignore

    total_names = new_names + old_names
    logger.info("start feedstock fetch loop")
    from .xonsh_utils import env

    debug = env.get("CONDA_FORGE_TICK_DEBUG", False)
    builder = _build_graph_sequential if debug else _build_graph_process_pool
    builder(gx, total_names, new_names)
    logger.info("feedstock fetch loop completed")

    gx2 = deepcopy(gx)
    logger.info("inferring nodes and edges")

    # make the outputs look up table so we can link properly
    outputs_lut = {
        k: node_name
        for node_name, node in gx.nodes.items()
        for k in node.get("payload", {}).get("outputs_names", [])
    }
    # add this as an attr so we can use later
    gx.graph["outputs_lut"] = outputs_lut
    strong_exports = {
        node_name
        for node_name, node in gx.nodes.items()
        if node.get("payload").get("strong_exports", False)
    }
    # This drops all the edge data and only keeps the node data
    gx = nx.create_empty_copy(gx)
    # TODO: label these edges with the kind of dep they are and their platform
    for node, node_attrs in gx2.nodes.items():
        with node_attrs["payload"] as attrs:
            # replace output package names with feedstock names via LUT
            deps = set(
                map(
                    lambda x: outputs_lut.get(x, x),
                    set().union(*attrs.get("requirements", {}).values()),
                )
            )

            # handle strong run exports
            overlap = deps & strong_exports
            requirements = attrs.get("requirements")
            if requirements:
                requirements["host"].update(overlap)
                requirements["run"].update(overlap)

        for dep in deps:
            if dep not in gx.nodes:
                # for packages which aren't feedstocks and aren't outputs
                # usually these are stubs
                lzj = LazyJson(f"node_attrs/{dep}.json")
                lzj.update(feedstock_name=dep, bad=False, archived=True)
                gx.add_node(dep, payload=lzj)
            gx.add_edge(dep, node)
    logger.info("new nodes and edges infered")
    return gx


def _get_last_updated_prs():
    query = textwrap.dedent("""
        {
          user(login: "regro-cf-autotick-bot") {
            pullRequests(first: 100, states: [CLOSED, MERGED], orderBy: {field: UPDATED_AT, direction: DESC} ) {
              totalCount
              nodes {
                closedAt
                createdAt
                number
                title
                databaseId
                baseRepository {
                  name
                }
              }
              pageInfo {
                hasNextPage
                endCursor
              }
            }
          }
        }
    """)  # noqa
    headers = {"Authorization": f"token {github_token}"}
    # Try several times because this times out
    for i in range(0):
        logger.info("graphQL request try %d", i+1)
        resp = requests.post(
            'https://api.github.com/graphql',
            json={'query': query},
            headers=headers,
        )
        if resp.status_code == 200 and 'data' in resp.json():
            data = resp.json()
            pr_ids = []
            for node in data['data']['user']['pullRequests']['nodes']:
                pr_ids.append(node['databaseId'])
            return pr_ids
        time.sleep(10)
    return []


def _update_pr(update_function, dry_run, gx):
    failed_refresh = 0
    succeeded_refresh = 0
    gh = "" if dry_run else github_client()
    futures = {}
    node_ids = list(gx.nodes)
    # this makes sure that github rate limits are dispersed
    random.shuffle(node_ids)

    pr_info_ordered = OrderedDict()
    if not dry_run:
        last_prs = _get_last_updated_prs()
    else:
        last_prs = []
    # Setting them here first gives them the highest priority in the OrderedDict
    for pr_id in last_prs:
        pr_info_ordered[pr_id] = None

    pr_json_regex = re.compile(r"^pr_json/([0-9]*).json$")
    with executor("thread", NUM_GITHUB_THREADS) as pool:
        for node_id in tqdm.tqdm(node_ids, desc='ordering PRs', leave=False):
            node = gx.nodes[node_id]["payload"]
            prs = node.get("PRed", [])
            for i, migration in enumerate(prs):
                pr_json = migration.get("PR", None)
                # allow for false
                if pr_json:
                    if '__lazy_json__' in pr_json:
                        m = pr_json_regex.match(pr_json['__lazy_json__'])
                        if m:
                            pr_id = int(m.group(1))
                        else:
                            pr_id = object()
                    else:
                        pr_id = object()
                    pr_info_ordered[pr_id] = (pr_json, node_id, i)

        for pr_id, v in pr_info_ordered.items():
            if v:
                (pr_json, node_id, i) = v
                future = pool.submit(update_function, ghctx, pr_json, gh, dry_run)
                futures[future] = (node_id, i)

        for f in as_completed(futures):
            name, i = futures[f]
            try:
                res = f.result()
                if res:
                    succeeded_refresh += 1
                    with gx.nodes[name]["payload"] as node:
                        node["PRed"][i]["PR"].update(**res)
                        # XXX: This is a bit of a hack
                        if update_function == close_out_labels:
                            node["PRed"][i]["data"]["bot_rerun"] = time.time()
                    logger.info(f"Updated json for {name}: {res['id']}")
            except github3.GitHubError as e:
                logger.error(f"GITHUB ERROR ON FEEDSTOCK: {name}")
                failed_refresh += 1
                if is_github_api_limit_reached(e, gh):
                    break
            except github3.exceptions.ConnectionError:
                logger.error(f"GITHUB ERROR ON FEEDSTOCK: {name}")
                failed_refresh += 1
            except Exception:
                logger.critical(
                    "ERROR ON FEEDSTOCK: {}: {}".format(
                        name, gx.nodes[name]["payload"]["PRed"][i],
                    ),
                )
                raise
    return succeeded_refresh, failed_refresh


def update_graph_pr_status(gx: nx.DiGraph, dry_run: bool = False) -> nx.DiGraph:
    succeeded_refresh, failed_refresh = _update_pr(refresh_pr, dry_run, gx)

    logger.info(f"JSON Refresh failed for {failed_refresh} PRs")
    logger.info(f"JSON Refresh succeed for {succeeded_refresh} PRs")
    return gx


def close_labels(gx: nx.DiGraph, dry_run: bool = False) -> nx.DiGraph:
    succeeded_refresh, failed_refresh = _update_pr(close_out_labels, dry_run, gx)

    logger.info(f"bot re-run failed for {failed_refresh} PRs")
    logger.info(f"bot re-run succeed for {succeeded_refresh} PRs")
    return gx


def main(args: "CLIArgs") -> None:
    setup_logger(logger)

    names = get_all_feedstocks(cached=True)
    if os.path.exists("graph.json"):
        gx = load_graph()
    else:
        gx = None
    gx = make_graph(names, gx)
    print(
        "nodes w/o payload:",
        [k for k, v in gx.nodes.items() if "payload" not in v],
    )
    # Utility flag for testing -- we don't need to always update GH
    no_github_fetch = os.environ.get("CONDA_FORGE_TICK_NO_GITHUB_REQUESTS")
    if not no_github_fetch:
        gx = close_labels(gx, args.dry_run)
        gx = update_graph_pr_status(gx, args.dry_run)

    logger.info("writing out file")
    dump_graph(gx)


if __name__ == "__main__":
    pass
    # main()
