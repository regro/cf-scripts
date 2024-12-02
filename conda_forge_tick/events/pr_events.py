import copy
import tempfile

from conda_forge_tick.git_utils import (
    close_out_dirty_prs,
    close_out_labels,
    github_client,
    refresh_pr,
)
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    dumps,
    get_sharded_path,
    lazy_json_override_backends,
)
from conda_forge_tick.utils import get_bot_run_url


def _react_to_pr(uid: str, dry_run: bool = False) -> None:
    updated_pr = False

    with lazy_json_override_backends(["github"], use_file_cache=False):
        pr_data = copy.deepcopy(LazyJson(f"pr_json/{uid}.json").data)

    with tempfile.TemporaryDirectory():
        with lazy_json_override_backends(["file"]):
            pr_json = LazyJson(f"pr_json/{uid}.json")
            with pr_json:
                pr_json.update(pr_data)

            with pr_json:
                pr_data = refresh_pr(pr_json, dry_run=dry_run)
                if not dry_run and pr_data is not None and pr_data != pr_json.data:
                    print("refreshed PR data", flush=True)
                    updated_pr = True
                    pr_json.update(pr_data)

            with pr_json:
                pr_data = close_out_labels(pr_json, dry_run=dry_run)
                if not dry_run and pr_data is not None and pr_data != pr_json.data:
                    print("closed PR due to bot-rerun label", flush=True)
                    updated_pr = True
                    pr_json.update(pr_data)

            with pr_json:
                pr_data = refresh_pr(pr_json, dry_run=dry_run)
                if not dry_run and pr_data is not None and pr_data != pr_json.data:
                    print("refreshed PR data", flush=True)
                    updated_pr = True
                    pr_json.update(pr_data)

            with pr_json:
                pr_data = close_out_dirty_prs(pr_json, dry_run=dry_run)
                if not dry_run and pr_data is not None and pr_data != pr_json.data:
                    print("closed PR due to merge conflicts", flush=True)
                    updated_pr = True
                    pr_json.update(pr_data)

            if not dry_run and updated_pr:
                gh = github_client()
                repo = gh.get_repo("regro/cf-graph-countyfair")
                fpath = get_sharded_path(f"pr_json/{uid}.json")
                message = f"event - pr {uid} - {get_bot_run_url()}"
                cnts = repo.get_contents(fpath)
                repo.update_file(
                    fpath,
                    message,
                    dumps(pr_json.data),
                    cnts.sha,
                )
                print("pushed PR update", flush=True)
            else:
                print("no changes to push", flush=True)


def react_to_pr(uid: str, dry_run: bool = False) -> None:
    """React to a PR event.

    Parameters
    ----------
    uid : str
        The unique identifier of the event. It is the PR id.
    dry_run : bool, optional
        If True, do not actually make any changes, by default False.
    """
    ntries = 10
    for nt in range(ntries):
        try:
            _react_to_pr(uid, dry_run=dry_run)
            break
        except Exception as e:
            print(
                "failed to push PR update - trying %d more times" % (ntries - nt - 1),
                flush=True,
            )
            if nt == ntries - 1:
                raise e
