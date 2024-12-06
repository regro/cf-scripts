import copy
import tempfile

from conda_forge_tick.git_utils import (
    close_out_dirty_prs,
    close_out_labels,
    parse_pr_json_last_updated,
    refresh_pr,
)
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    lazy_json_override_backends,
    push_lazy_json_via_gh_api,
)
from conda_forge_tick.os_utils import pushd


def _react_to_pr(uid: str, dry_run: bool = False) -> None:
    updated_pr = False

    with lazy_json_override_backends(["github"], use_file_cache=False):
        pr_data = copy.deepcopy(LazyJson(f"pr_json/{uid}.json").data)

    last_updated = parse_pr_json_last_updated(pr_data)

    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(str(tmpdir)),
        lazy_json_override_backends(["file"]),
    ):
        pr_json = LazyJson(f"pr_json/{uid}.json")
        with pr_json:
            pr_json.update(pr_data)

        with pr_json:
            pr_data = refresh_pr(pr_json, dry_run=dry_run)
            if pr_data is not None:
                new_last_updated = parse_pr_json_last_updated(pr_data)
            if (
                last_updated is not None
                and new_last_updated is not None
                and new_last_updated < last_updated
            ):
                print(
                    f"PR data from GitHub API is stale ('{new_last_updated.isoformat()}' "
                    f"is before '{last_updated.isoformat()}') - skipping update!",
                    flush=True,
                )
                return
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
            push_lazy_json_via_gh_api(pr_json)
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
