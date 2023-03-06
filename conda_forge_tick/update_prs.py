import logging
import os
import random
import re
import typing
from concurrent.futures._base import as_completed
import hashlib

import github3
import networkx as nx
import tqdm

# from conda_forge_tick.profiler import profiling

from conda_forge_tick.git_utils import (
    close_out_labels,
    is_github_api_limit_reached,
    refresh_pr,
    close_out_dirty_prs,
)
from .make_graph import ghctx
from .utils import (
    setup_logger,
    load_graph,
    github_client,
    executor,
)

if typing.TYPE_CHECKING:
    from .cli import CLIArgs

logger = logging.getLogger("conda_forge_tick.update_prs")

NUM_GITHUB_THREADS = 2
KEEP_PR_FRACTION = 1.5


PR_JSON_REGEX = re.compile(r"^pr_json/([0-9]*).json$")


def _update_pr(update_function, dry_run, gx, job, n_jobs):
    failed_refresh = 0
    succeeded_refresh = 0
    gh = "" if dry_run else github_client()
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
            desc="submiting PR refresh jobs",
            leave=False,
        ):
            node = gx.nodes[node_id]["payload"]
            for kind, prs in [
                ("pr_info", node["pr_info"].get("PRed", [])),
                ("version_pr_info", node["version_pr_info"].get("PRed", [])),
            ]:
                for i, migration in enumerate(prs):

                    if random.uniform(0, 1) >= KEEP_PR_FRACTION:
                        continue

                    pr_json = migration.get("PR", None)

                    if pr_json and not pr_json["state"] == "closed":
                        future = pool.submit(
                            update_function,
                            ghctx,
                            pr_json,
                            gh,
                            dry_run,
                        )
                        futures[future] = (node_id, i, pr_json, kind)

        for f in tqdm.tqdm(
            as_completed(futures),
            total=len(futures),
            desc="gathering PR data",
            leave=False,
        ):
            name, i, pr_json, pr_kind = futures[f]
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
                    pr_json.update(**res)
            except github3.GitHubError as e:
                logger.error(f"GITHUB ERROR ON FEEDSTOCK: {name}")
                failed_refresh += 1
                if is_github_api_limit_reached(e, gh):
                    break
            except github3.exceptions.ConnectionError:
                logger.error(f"GITHUB ERROR ON FEEDSTOCK: {name}")
                failed_refresh += 1
            except Exception:
                import traceback

                logger.critical(
                    "ERROR ON FEEDSTOCK: {}: {} - {}".format(
                        name,
                        gx.nodes[name]["payload"][pr_kind]["PRed"][i],
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


# @profiling
def main(args: "CLIArgs") -> None:
    setup_logger(logger)

    if os.path.exists("graph.json"):
        gx = load_graph()
    else:
        gx = None

    if not args.dry_run:
        gx = close_labels(gx, args.dry_run, job=args.job, n_jobs=args.n_jobs)
        gx = update_graph_pr_status(gx, args.dry_run, job=args.job, n_jobs=args.n_jobs)
        # This function needs to run last since it edits the actual pr json!
        gx = close_dirty_prs(gx, args.dry_run, job=args.job, n_jobs=args.n_jobs)


if __name__ == "__main__":
    pass
    # main()
