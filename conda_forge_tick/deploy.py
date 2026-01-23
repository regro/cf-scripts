import logging
import os
import secrets
import subprocess
import sys
import time

from .git_utils import (
    delete_file_via_gh_api,
    get_bot_token,
    push_file_via_gh_api,
    reset_and_restore_file,
)
from .lazy_json_backends import (
    CF_TICK_GRAPH_DATA_HASHMAPS,
    get_lazy_json_backends,
)
from .os_utils import clean_disk_space
from .settings import settings
from .utils import (
    fold_log_lines,
    get_bot_run_url,
    load_existing_graph,
    run_command_hiding_token,
)

logger = logging.getLogger(__name__)

RNG = secrets.SystemRandom()


def _flush_io():
    sys.stdout.flush()
    sys.stderr.flush()


def _run_git_cmd(cmd, **kwargs):
    r = subprocess.run(["git"] + cmd, check=True, **kwargs)
    _flush_io()
    return r


def _parse_gh_conflicts(output):
    files_to_commit = []
    in_section = False
    indent = None
    for line in output.splitlines():
        print(line, flush=True)
        if not line.strip():
            continue

        if line.startswith("error:"):
            in_section = True
            continue

        if in_section and indent is not None and not line.startswith(indent):
            in_section = False
            indent = None
            continue

        if in_section:
            if indent is None:
                indent = line[: len(line) - len(line.lstrip())]
            fname = line.strip()
            if os.path.exists(fname):
                files_to_commit.append(fname)
            continue

    return files_to_commit


def _pull_changes(batch):
    r = subprocess.run(
        ["git", "pull", "-s", "recursive", "-X", "theirs"],
        text=True,
        capture_output=True,
    )
    n_added = 0
    if r.returncode != 0:
        files_to_commit = _parse_gh_conflicts(r.stderr + "\n" + r.stdout)

        for fname in files_to_commit:
            n_added += 1
            print(f"committing for conflicts {n_added: >5d}: {fname}", flush=True)
            _run_git_cmd(["add", fname])

        if files_to_commit:
            _step_name = os.environ.get("GITHUB_WORKFLOW", "update graph")
            _run_git_cmd(
                [
                    "commit",
                    "-m",
                    f"{_step_name} - conflicts for batch {batch: >3d} - {get_bot_run_url()}",
                ],
            )

        _run_git_cmd(["pull", "-s", "recursive", "-X", "theirs"])

    _flush_io()

    return n_added


def _deploy_batch(
    *,
    files_to_add: set[str],
    batch,
    n_added,
    max_per_batch=200,
    exp_backoff_base: float = 1.1,
    exp_backoff_rfrac: float = 0.5,
    max_tries: int = 30,
):
    n_added_this_batch = 0
    while files_to_add and n_added_this_batch < max_per_batch:
        file = files_to_add.pop()
        if file and os.path.exists(file):
            try:
                print(f"committing {n_added: >5d}: {file}", flush=True)
                _run_git_cmd(["add", file])
                n_added_this_batch += 1
                n_added += 1
            except Exception as e:
                print(e, flush=True)

    if n_added_this_batch > 0:
        try:
            _step_name = os.environ.get("GITHUB_WORKFLOW", "update graph")
            _run_git_cmd(
                [
                    "commit",
                    "-m",
                    f"{_step_name} - batch {batch: >3d} - {get_bot_run_url()}",
                ],
            )
        except Exception as e:
            print(e, flush=True)

        status = 1
        num_try = 0
        while status != 0 and num_try < max_tries:
            with fold_log_lines(">>>>>>>>>>>> git pull+push try %d" % num_try):
                try:
                    # pull twice right away to reduce chance of changes between
                    # pull and push
                    for pull_itr in range(2):
                        print(">>>>>>>>>>>> git pull %d/2" % (pull_itr + 1), flush=True)
                        _n_added = _pull_changes(batch)
                        n_added += _n_added
                        n_added_this_batch += _n_added
                except Exception as e:
                    print(
                        ">>>>>>>>>>>> git pull failed: %s" % repr(e),
                        flush=True,
                    )
                    pass

                print(">>>>>>>>>>>> git push try", flush=True)
                status = run_command_hiding_token(
                    [
                        "git",
                        "push",
                        f"https://{get_bot_token()}@github.com/{settings().graph_github_backend_repo}.git",
                        settings().graph_repo_default_branch,
                    ],
                    token=get_bot_token(),
                )
                if status != 0:
                    print(">>>>>>>>>>>> git push failed", flush=True)
                    interval = exp_backoff_base**num_try
                    interval = interval * exp_backoff_rfrac * (1.0 + RNG.uniform(0, 1))
                    time.sleep(interval)
            num_try += 1

        if status != 0:
            # we did try to push to a branch but it never worked so we'll just stop
            raise RuntimeError("bot did not push its data! stopping!")

    return n_added_this_batch


def _get_files_to_delete() -> set[str]:
    r = subprocess.run(
        ["git", "diff", "--name-status", "--cached"],
        text=True,
        capture_output=True,
        check=True,
    )
    files_to_delete = set()
    for line in r.stdout.splitlines():
        res = line.strip().split()
        if len(res) < 2:
            continue
        status, fname = res[0:2]
        if status == "D":
            files_to_delete.add(fname)
    return files_to_delete


def _get_pth_commit_message(pth):
    """Make a nice message for stuff managed via LazyJson."""
    step_name = os.environ.get("GITHUB_WORKFLOW", "update graph")
    msg_pth = pth
    parts = pth.split("/")
    if pth.endswith(".json") and (
        len(parts) > 1 and parts[0] in CF_TICK_GRAPH_DATA_HASHMAPS
    ):
        msg_pth = f"{parts[0]}/{parts[-1]}"
    msg = f"{step_name} - {msg_pth} - {get_bot_run_url()}"
    return msg


def _deploy_via_api(
    do_git_ops: bool,
    files_to_add: set[str],
    files_to_delete: set[str],
    files_done: set[str],
    files_to_try_again: set[str],
) -> tuple[bool, set[str], set[str], set[str]]:
    if len(files_to_add) + len(files_to_delete) <= 200:
        for pth in files_to_add:
            if do_git_ops:
                break

            try:
                print(
                    f"pushing file '{pth}' to the graph via the GitHub API", flush=True
                )

                msg = _get_pth_commit_message(pth)

                push_file_via_gh_api(pth, settings().graph_github_backend_repo, msg)
            except Exception as e:
                logger.warning(
                    "git push via API failed - trying via git CLI", exc_info=e
                )
                do_git_ops = True
                files_to_try_again.add(pth)
            else:
                files_done.add(pth)

        for pth in files_to_delete:
            if do_git_ops:
                break

            try:
                print(
                    f"deleting file '{pth}' from the graph via the GitHub API",
                    flush=True,
                )

                # make a nice message for stuff managed via LazyJson
                msg = _get_pth_commit_message(pth)

                delete_file_via_gh_api(pth, settings().graph_github_backend_repo, msg)
            except Exception as e:
                logger.warning(
                    "git delete via API failed - trying via git CLI", exc_info=e
                )
                do_git_ops = True
            else:
                files_done.add(pth)

    else:
        do_git_ops = True

    for pth in files_done:
        reset_and_restore_file(pth)

    return do_git_ops, files_to_add, files_done, files_to_try_again


def deploy(
    dry_run: bool = False,
    dirs_to_deploy: list[str] | None = None,
    git_only: bool = False,
    dirs_to_ignore: list[str] | None = None,
):
    if dry_run:
        print("(dry run) deploying", flush=True)
        return

    # make sure the graph can load, if not it will error
    gx = load_existing_graph()
    # TODO: be more selective about which json to check
    for node, attrs in gx.nodes.items():
        with attrs["payload"]:
            pass

    with fold_log_lines("cleaning up disk space for deploy"):
        clean_disk_space()

    files_to_add: set[str] = set()
    if dirs_to_deploy is None:
        drs_to_deploy = [
            "status",
            "mappings",
            "mappings/pypi",
            "ranked_hubs_authorities.json",
            "all_feedstocks.json",
            "import_to_pkg_maps",
        ]
        if "file" in get_lazy_json_backends():
            drs_to_deploy += CF_TICK_GRAPH_DATA_HASHMAPS
            drs_to_deploy += ["graph.json"]
    else:
        if dirs_to_ignore is not None:
            raise RuntimeError(
                "You cannot specify both `dirs_to_deploy` "
                "and `dirs_to_ignore` when deploying the graph!"
            )
        drs_to_deploy = dirs_to_deploy

    for dr in drs_to_deploy:
        if not os.path.exists(dr):
            continue

        # untracked
        files_to_add |= set(
            _run_git_cmd(
                ["ls-files", "-o", "--exclude-standard", dr],
                capture_output=True,
                text=True,
            ).stdout.splitlines(),
        )

        # changed
        files_to_add |= set(
            _run_git_cmd(
                ["diff", "--name-only", dr],
                capture_output=True,
                text=True,
            ).stdout.splitlines(),
        )

        # modified and staged but not deleted
        files_to_add |= set(
            _run_git_cmd(
                ["diff", "--name-only", "--cached", "--diff-filter=d", dr],
                capture_output=True,
                text=True,
            ).stdout.splitlines(),
        )

    files_to_delete = _get_files_to_delete()

    if dirs_to_ignore is not None:
        print("ignoring dirs:", dirs_to_ignore, flush=True)
        new_files_to_add = set()
        for fn in files_to_add:
            if any(fn.startswith(f"{dr}/") for dr in dirs_to_ignore):
                reset_and_restore_file(fn)
                print("ignoring file to add:", fn, flush=True)
            else:
                new_files_to_add.add(fn)
        files_to_add = new_files_to_add

        new_files_to_delete = set()
        for fn in files_to_delete:
            if any(fn.startswith(f"{dr}/") for dr in dirs_to_ignore):
                reset_and_restore_file(fn)
                print("ignoring file to delete:", fn, flush=True)
            else:
                new_files_to_delete.add(fn)
        files_to_delete = new_files_to_delete

    print("found %d files to add" % len(files_to_add), flush=True)
    print("found %d files to delete" % len(files_to_delete), flush=True)

    do_git_ops = False
    files_to_try_again: set[str] = set()
    files_done: set[str] = set()
    if not git_only:
        (do_git_ops, files_to_add, files_done, files_to_try_again) = _deploy_via_api(
            do_git_ops, files_to_add, files_to_delete, files_done, files_to_try_again
        )

    batch = 0
    if do_git_ops or git_only:
        files_to_add = (files_to_add - files_done) | files_to_try_again
        n_added = 0
        while files_to_add:
            batch += 1
            n_added += _deploy_batch(
                files_to_add=files_to_add,
                n_added=n_added,
                batch=batch,
            )

        print(f"deployed {n_added} files to graph in {batch} batches", flush=True)
    else:
        if files_done:
            _pull_changes(batch)
