import copy
import hashlib
import logging
import secrets
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
from conda_forge_tick.utils import get_keys_default

from .executors import executor
from .utils import load_existing_graph

# from conda_forge_tick.profiler import profiling

logger = logging.getLogger(__name__)

RNG = secrets.SystemRandom()

NUM_GITHUB_THREADS = 2
KEEP_PR_FRACTION = 0.5


def _combined_update_function(
    pr_json: dict, dry_run: bool, remake_prs_with_conflicts: bool
) -> dict:
    return_it = False

    pr_data = refresh_pr(pr_json, dry_run=dry_run)
    if pr_data is not None:
        return_it = True
        pr_json.update(pr_data)

    pr_data = close_out_labels(pr_json, dry_run=dry_run)
    if pr_data is not None:
        return_it = True
        pr_json.update(pr_data)

    if remake_prs_with_conflicts:
        pr_data = refresh_pr(pr_json, dry_run=dry_run)
        if pr_data is not None:
            return_it = True
            pr_json.update(pr_data)

        pr_data = close_out_dirty_prs(pr_json, dry_run=dry_run)
        if pr_data is not None:
            return_it = True
            pr_json.update(pr_data)

    if return_it:
        return pr_json
    else:
        return None


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
    RNG.shuffle(node_ids)

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

            remake_prs_with_conflicts = get_keys_default(
                node,
                ["conda-forge.yml", "bot", "remake_prs_with_conflicts"],
                {},
                True,
            )

            prs = node.get("pr_info", {}).get("PRed", [])
            for i, migration in enumerate(prs):
                if RNG.random() >= KEEP_PR_FRACTION:
                    continue

                pr_json = migration.get("PR", None)

                if pr_json and pr_json["state"] != "closed":
                    _pr_json = copy.deepcopy(pr_json.data)
                    future = pool.submit(
                        update_function, _pr_json, dry_run, remake_prs_with_conflicts
                    )
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
                        "Last-Modified" in pr_json
                        and "Last-Modified" in res
                        and pr_json["Last-Modified"] != res["Last-Modified"]
                    ):
                        tqdm.tqdm.write(f"Updated PR json for {name}: {res['id']}")
                    with pr_json as attrs:
                        attrs.update(**res)
            except (github3.GitHubError, github.GithubException) as e:
                logger.error("GITHUB ERROR ON FEEDSTOCK: %s", name)
                failed_refresh += 1
                if is_github_api_limit_reached():
                    logger.warning("GitHub API error", exc_info=e)
                    break
            except (github3.exceptions.ConnectionError, github.GithubException):
                logger.error("GITHUB ERROR ON FEEDSTOCK: %s", name)
                failed_refresh += 1
            except Exception:
                logger.critical(
                    "ERROR ON FEEDSTOCK: %s: %s",
                    name,
                    gx.nodes[name]["payload"]["pr_info"]["PRed"][i],
                    exc_info=True,
                )
                raise

    return succeeded_refresh, failed_refresh


def update_pr_combined(
    gx: nx.DiGraph,
    dry_run: bool = False,
    job=1,
    n_jobs=1,
) -> nx.DiGraph:
    succeeded_refresh, failed_refresh = _update_pr(
        _combined_update_function, dry_run, gx, job, n_jobs
    )

    logger.info("JSON Refresh failed for %d PRs", failed_refresh)
    logger.info("JSON Refresh succeed for %d PRs", succeeded_refresh)
    return gx


def main(ctx: CliContext, job: int = 1, n_jobs: int = 1) -> None:
    gx = load_existing_graph()
    update_pr_combined(gx, ctx.dry_run, job=job, n_jobs=n_jobs)
