import copy
import hashlib
import logging
import secrets
import time
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
from conda_forge_tick.utils import get_keys_default, pr_can_be_archived

from .executors import executor
from .utils import load_existing_graph

# from conda_forge_tick.profiler import profiling

logger = logging.getLogger(__name__)

RNG = secrets.SystemRandom()

NUM_GITHUB_THREADS = 2
KEEP_PR_FRACTION = 0.125


def _combined_update_function(
    pr_json: dict, dry_run: bool, remake_prs_with_conflicts: bool
) -> dict | None:
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
    return None


# as a separate function for easier coverage testing without triggering
# _update_pr, we can still test _update_pr with no
# matching nodes and it returns 0,0 immediately.
def _filter_feedstock_nodes(node_ids, feedstock_filter):
    """Filter node IDs to match a specific feedstock.

    Parameters
    ----------
    node_ids : list of str
        List of all node IDs in the graph.
    feedstock_filter : str or None
        The feedstock name to filter for (must include "-feedstock" suffix).

    Returns
    -------
    list of str
        Filtered node IDs matching the feedstock.
    """
    if not feedstock_filter:
        return node_ids

    return [node_id for node_id in node_ids if node_id == feedstock_filter]


def _update_pr(update_function, dry_run, gx, job, n_jobs, feedstock_filter=None):
    failed_refresh = 0
    succeeded_refresh = 0
    futures = {}
    node_ids = list(gx.nodes)

    # Apply feedstock filter if provided
    # When filtering to a specific feedstock, disable random sampling
    node_ids = _filter_feedstock_nodes(node_ids, feedstock_filter)
    if feedstock_filter and not node_ids:
        logger.warning("No feedstock found matching: %s", feedstock_filter)
        return 0, 0

    job_index = job - 1
    node_ids = [
        node_id
        for node_id in node_ids
        if abs(int(hashlib.sha1(node_id.encode("utf-8")).hexdigest(), 16)) % n_jobs
        == job_index
    ]
    now = time.time()

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
                # Skip random sampling if a specific feedstock is selected
                if not feedstock_filter and RNG.random() >= KEEP_PR_FRACTION:
                    continue

                pr_json = migration.get("PR", None)

                if pr_json and (not pr_can_be_archived(pr_json, now=now)):
                    _pr_json = copy.deepcopy(pr_json.data)
                    future = pool.submit(
                        update_function,
                        _pr_json,
                        dry_run,
                        remake_prs_with_conflicts,
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
    feedstock: str | None = None,
) -> nx.DiGraph:
    """Update PRs in the graph.

    Parameters
    ----------
    gx : nx.DiGraph
        The graph containing feedstock nodes.
    dry_run : bool, optional
        If True, don't actually update PRs on GitHub. Default is False.
    job : int, optional
        The job number (1-indexed) for parallel processing. Default is 1.
    n_jobs : int, optional
        The total number of jobs for parallel processing. Default is 1.
    feedstock : str | None, optional
        If provided, only update PRs for this specific feedstock.
        Must end with "-feedstock" suffix (validated in main()).

    Returns
    -------
    nx.DiGraph
        The updated graph.
    """
    succeeded_refresh, failed_refresh = _update_pr(
        _combined_update_function, dry_run, gx, job, n_jobs, feedstock_filter=feedstock
    )

    logger.info("JSON Refresh failed for %d PRs", failed_refresh)
    logger.info("JSON Refresh succeed for %d PRs", succeeded_refresh)
    return gx


def main(
    ctx: CliContext, job: int = 1, n_jobs: int = 1, feedstock: str | None = None
) -> None:
    if feedstock and not feedstock.endswith("-feedstock"):
        raise ValueError(
            f"Feedstock name must end with '-feedstock': got '{feedstock}', "
            f"expected '{feedstock}-feedstock'"
        )

    gx = load_existing_graph()
    update_pr_combined(gx, ctx.dry_run, job=job, n_jobs=n_jobs, feedstock=feedstock)
