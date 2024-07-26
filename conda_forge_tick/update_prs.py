import copy
import hashlib
import logging
import random
from concurrent.futures._base import as_completed

import github
import github3
import networkx as nx
import tqdm

from conda_forge_tick.cli_context import CliContext
from conda_forge_tick.git_utils import (
    close_out_dirty_prs,
    close_out_labels,
    is_github_api_limit_reached,
    refresh_pr,
)

from .executors import executor
from .utils import load_existing_graph

# from conda_forge_tick.profiler import profiling

logger = logging.getLogger(__name__)

NUM_GITHUB_THREADS = 2
KEEP_PR_FRACTION = 0.5


def _update_pr(update_function, dry_run, gx, job, n_jobs):
    failed_refresh = 0
    succeeded_refresh = 0
    futures = {}
    node_ids = list(gx.nodes)
    job_index = job - 1
    node_ids = [
        node_id
        for node_id in node_ids
        if abs(int(hashlib.sha1(node_id.encode("utf-8")).hexdigest(), 16)) % n_jobs
        == job_index
    ]

    # this makes sure that github rate limits are dispersed
    random.shuffle(node_ids)

    with executor("thread", NUM_GITHUB_THREADS) as pool:
        for node_id in tqdm.tqdm(
            node_ids,
            desc="submitting PR refresh jobs",
            leave=False,
            ncols=80,
        ):
            node = gx.nodes[node_id]["payload"]
            if node.get("archived", False):
                continue
            prs = node.get("pr_info", {}).get("PRed", [])
            for i, migration in enumerate(prs):
                if random.uniform(0, 1) >= KEEP_PR_FRACTION:
                    continue

                pr_json = migration.get("PR", None)

                if pr_json and pr_json["state"] != "closed":
                    _pr_json = copy.deepcopy(pr_json.data)
                    future = pool.submit(update_function, _pr_json, dry_run)
                    futures[future] = (node_id, i, pr_json)

        for f in tqdm.tqdm(
            as_completed(futures),
            total=len(futures),
            desc="gathering PR data",
            leave=False,
            ncols=80,
        ):
            name, i, pr_json = futures[f]
            try:
                res = f.result()
                if res:
                    succeeded_refresh += 1
                    if (
                        "ETag" in pr_json
                        and "ETag" in res
                        and pr_json["ETag"] != res["ETag"]
                    ):
                        tqdm.tqdm.write(f"Updated PR json for {name}: {res['id']}")
                    with pr_json as attrs:
                        attrs.update(**res)
            except (github3.GitHubError, github.GithubException) as e:
                logger.error(f"GITHUB ERROR ON FEEDSTOCK: {name}")
                failed_refresh += 1
                if is_github_api_limit_reached():
                    logger.warning("GitHub API error", exc_info=e)
                    break
            except (github3.exceptions.ConnectionError, github.GithubException):
                logger.error(f"GITHUB ERROR ON FEEDSTOCK: {name}")
                failed_refresh += 1
            except Exception:
                import traceback

                logger.critical(
                    "ERROR ON FEEDSTOCK: {}: {} - {}".format(
                        name,
                        gx.nodes[name]["payload"]["pr_info"]["PRed"][i],
                        traceback.format_exc(),
                    ),
                )
                raise

    return succeeded_refresh, failed_refresh


def update_graph_pr_status(
    gx: nx.DiGraph,
    dry_run: bool = False,
    job=1,
    n_jobs=1,
) -> nx.DiGraph:
    succeeded_refresh, failed_refresh = _update_pr(refresh_pr, dry_run, gx, job, n_jobs)

    logger.info(f"JSON Refresh failed for {failed_refresh} PRs")
    logger.info(f"JSON Refresh succeed for {succeeded_refresh} PRs")
    return gx


def close_labels(
    gx: nx.DiGraph,
    dry_run: bool = False,
    job=1,
    n_jobs=1,
) -> nx.DiGraph:
    succeeded_refresh, failed_refresh = _update_pr(
        close_out_labels,
        dry_run,
        gx,
        job,
        n_jobs,
    )

    logger.info(f"bot re-run failed for {failed_refresh} PRs")
    logger.info(f"bot re-run succeed for {succeeded_refresh} PRs")
    return gx


def close_dirty_prs(
    gx: nx.DiGraph,
    dry_run: bool = False,
    job=1,
    n_jobs=1,
) -> nx.DiGraph:
    succeeded_refresh, failed_refresh = _update_pr(
        close_out_dirty_prs,
        dry_run,
        gx,
        job,
        n_jobs,
    )

    logger.info(f"close dirty PRs failed for {failed_refresh} PRs")
    logger.info(f"close dirty PRs succeed for {succeeded_refresh} PRs")
    return gx


def main(ctx: CliContext, job: int = 1, n_jobs: int = 1) -> None:
    gx = load_existing_graph()

    gx = close_labels(gx, ctx.dry_run, job=job, n_jobs=n_jobs)
    gx = update_graph_pr_status(gx, ctx.dry_run, job=job, n_jobs=n_jobs)
    # This function needs to run last since it edits the actual pr json!
    gx = close_dirty_prs(gx, ctx.dry_run, job=job, n_jobs=n_jobs)
