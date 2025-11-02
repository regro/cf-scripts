import copy
import time

import dateparser

from conda_forge_tick.git_utils import (
    close_out_dirty_prs,
    close_out_labels,
    refresh_pr,
)
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    lazy_json_override_backends,
)
from conda_forge_tick.utils import get_keys_default


def _backout_node_from_html_url(html_url):
    """Get the node name from a URL like `https://github.com/conda-forge/pygraphblas-feedstock/pull/17`."""
    return html_url.split("/conda-forge/")[1].split("/")[0].rsplit("-", maxsplit=1)[0]


def _react_to_pr(uid: str, dry_run: bool = False) -> None:
    with lazy_json_override_backends(["github_api"], use_file_cache=False):
        pr_json = LazyJson(f"pr_json/{uid}.json")

        with pr_json:
            if pr_json.get("html_url", None) is not None:
                node_name = _backout_node_from_html_url(pr_json.get("html_url", None))
                node = LazyJson(f"node_attrs/{node_name}.json")
                remake_prs_with_conflicts = get_keys_default(
                    node,
                    ["conda-forge.yml", "bot", "remake_prs_with_conflicts"],
                    {},
                    True,
                )
            else:
                remake_prs_with_conflicts = True

            now = time.time()
            dt = 15.0 * 60.0  # 15 minutes in seconds
            pr_lm = pr_json.get("Last-Modified", None)
            if pr_lm is not None:
                pr_lm = dateparser.parse(pr_lm)

            # if the PR is not closed or was closed less than 15 minutes ago
            # we attempt to refresh the data
            if pr_json.get("state", None) != "closed" or (
                pr_json.get("state", None) == "closed"
                and pr_lm is not None
                and now - pr_lm <= dt
            ):
                pr_data = refresh_pr(copy.deepcopy(pr_json.data), dry_run=dry_run)
                if pr_data is not None:
                    if (
                        "Last-Modified" in pr_json
                        and "Last-Modified" in pr_data
                        and pr_json["Last-Modified"] != pr_data["Last-Modified"]
                    ):
                        print("refreshed PR data", flush=True)
                    pr_json.update(pr_data)

            if pr_json.get("state", None) != "closed":
                pr_data = close_out_labels(copy.deepcopy(pr_json.data), dry_run=dry_run)
                if pr_data is not None:
                    if (
                        "Last-Modified" in pr_json
                        and "Last-Modified" in pr_data
                        and pr_json["Last-Modified"] != pr_data["Last-Modified"]
                    ):
                        print("closed PR due to bot-rerun label", flush=True)
                    pr_json.update(pr_data)

            if remake_prs_with_conflicts:
                if pr_json.get("state", None) != "closed":
                    pr_data = refresh_pr(copy.deepcopy(pr_json.data), dry_run=dry_run)
                    if pr_data is not None:
                        if (
                            "Last-Modified" in pr_json
                            and "Last-Modified" in pr_data
                            and pr_json["Last-Modified"] != pr_data["Last-Modified"]
                        ):
                            print("refreshed PR data", flush=True)
                        pr_json.update(pr_data)

                if pr_json.get("state", None) != "closed":
                    pr_data = close_out_dirty_prs(
                        copy.deepcopy(pr_json.data), dry_run=dry_run
                    )
                    if pr_data is not None:
                        if (
                            "Last-Modified" in pr_json
                            and "Last-Modified" in pr_data
                            and pr_json["Last-Modified"] != pr_data["Last-Modified"]
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
