import os
import subprocess

from . import sensitive_env
from .cli_context import CliContext
from .lazy_json_backends import CF_TICK_GRAPH_DATA_HASHMAPS, get_lazy_json_backends
from .utils import get_bot_run_url, load_existing_graph, run_command_hiding_token


def _run_git_cmd(cmd, **kwargs):
    return subprocess.run(["git"] + cmd, check=True, **kwargs)


def _deploy_batch(*, files_to_add, batch, n_added, max_per_batch=200):
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
                print(e)

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
            print(e)

        # make sure the graph can load, if not we will error
        try:
            gx = load_existing_graph()
            # TODO: be more selective about which json to check
            for node, attrs in gx.nodes.items():
                attrs["payload"]._load()
            graph_ok = True
        except Exception:
            graph_ok = False

        status = 1
        num_try = 0
        while status != 0 and num_try < 10 and graph_ok:
            try:
                print("\n\n>>>>>>>>>>>> git pull try %d\n\n" % num_try, flush=True)
                _run_git_cmd(["pull", "-s", "recursive", "-X", "theirs"])
            except Exception as e:
                print(
                    "\n\n>>>>>>>>>>>> git pull try %d failed: %s \n\n" % (num_try, e),
                    flush=True,
                )
                pass
            print("\n\n>>>>>>>>>>>> git push try %d\n\n" % num_try, flush=True)
            with sensitive_env() as env:
                status = run_command_hiding_token(
                    [
                        "git",
                        "push",
                        "https://{token}@github.com/{deploy_repo}.git".format(
                            token=env.get("BOT_TOKEN", ""),
                            deploy_repo="regro/cf-graph-countyfair",
                        ),
                        "master",
                    ],
                    token=env.get("BOT_TOKEN", ""),
                )
            num_try += 1

        if status != 0 or not graph_ok:
            # we did try to push to a branch but it never worked so we'll just stop
            raise RuntimeError("bot did not push its data! stopping!")

    return n_added_this_batch


def deploy(ctx: CliContext, dirs_to_deploy: list[str] = None):
    """Deploy the graph to GitHub"""
    if ctx.dry_run:
        print("(dry run) deploying")
        return

    # pull changes, add ours, make a commit
    try:
        _run_git_cmd(["pull", "-s", "recursive", "-X", "theirs"])
    except Exception as e:
        print(e)

    files_to_add = set()
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

    print("found %d files to add" % len(files_to_add), flush=True)

    n_added = 0
    batch = 0
    while files_to_add:
        batch += 1
        n_added += _deploy_batch(
            files_to_add=files_to_add,
            n_added=n_added,
            batch=batch,
        )

    print(f"deployed {n_added} files to graph in {batch} batches", flush=True)
