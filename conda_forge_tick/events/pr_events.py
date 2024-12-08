import copy

from conda_forge_tick.git_utils import (
    close_out_dirty_prs,
    close_out_labels,
    refresh_pr,
)
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    lazy_json_override_backends,
)


def _react_to_pr(uid: str, dry_run: bool = False) -> None:
    with lazy_json_override_backends(["github_api"], use_file_cache=False):
        pr_json = LazyJson(f"pr_json/{uid}.json")

        with pr_json:
            if pr_json["state"] != "closed":
                pr_data = close_out_labels(copy.deepcopy(pr_json.data), dry_run=dry_run)
                if pr_data is not None:
                    if (
                        "ETag" in pr_json
                        and "ETag" in pr_data
                        and pr_json["ETag"] != pr_data["ETag"]
                    ):
                        print("closed PR due to bot-rerun label", flush=True)
                    pr_json.update(pr_data)

            if pr_json["state"] != "closed":
                pr_data = refresh_pr(copy.deepcopy(pr_json.data), dry_run=dry_run)
                if pr_data is not None:
                    if (
                        "ETag" in pr_json
                        and "ETag" in pr_data
                        and pr_json["ETag"] != pr_data["ETag"]
                    ):
                        print("refreshed PR data", flush=True)
                    pr_json.update(pr_data)

            if pr_json["state"] != "closed":
                pr_data = close_out_dirty_prs(
                    copy.deepcopy(pr_json.data), dry_run=dry_run
                )
                if pr_data is not None:
                    if (
                        "ETag" in pr_json
                        and "ETag" in pr_data
                        and pr_json["ETag"] != pr_data["ETag"]
                    ):
                        print("closed PR due to merge conflicts", flush=True)
                    pr_json.update(pr_data)


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
