import argparse
import importlib
import os
import subprocess
import time

from doctr.travis import run_command_hiding_token as doctr_run

from . import sensitive_env
from .utils import load_graph

BUILD_URL_KEY = "CIRCLE_BUILD_URL"

INT_SCRIPT_DICT = {
    0: {"module": "all_feedstocks", "func": "main"},
    1: {"module": "make_graph", "func": "main"},
    2: {"module": "update_upstream_versions", "func": "main"},
    3: {"module": "auto_tick", "func": "main"},
    4: {"module": "status_report", "func": "main"},
    5: {"module": "audit", "func": "main"},
    6: {"module": "update_prs", "func": "main"},
    7: {"module": "mappings", "func": "main"},
}


def _run_git_cmd(cmd):
    return subprocess.run(cmd, shell=True, check=True)


def deploy(args):
    """Deploy the graph to github"""
    if args.dry_run:
        print("(dry run) deploying")
        return

    # TODO: have function construct this
    BUILD_URL = os.environ.get(BUILD_URL_KEY, "")

    # pull changes, add ours, make a commit
    try:
        _run_git_cmd("git pull -s recursive -X theirs")
    except Exception as e:
        print(e)

    files_to_add = set()
    for dr in [
        "pr_json",
        "status",
        "node_attrs",
        "audits",
        "audits/grayskull",
        "audits/depfinder",
        "versions",
        "profiler",
        "mappings",
        "mappings/pypi",
        "ranked_hubs_authorities.json",
    ]:
        # untracked
        files_to_add |= set(
            subprocess.run(
                f"git ls-files -o --exclude-standard {dr}",
                shell=True,
                capture_output=True,
            )
            .stdout.decode("utf-8")
            .splitlines(),
        )

        # changed
        files_to_add |= set(
            subprocess.run(
                f"git diff --name-only {dr}",
                shell=True,
                capture_output=True,
            )
            .stdout.decode("utf-8")
            .splitlines(),
        )

        # modified and staged but not deleted
        files_to_add |= set(
            subprocess.run(
                f"git diff --name-only --cached --diff-filter=d {dr}",
                shell=True,
                capture_output=True,
            )
            .stdout.decode("utf-8")
            .splitlines(),
        )

    n_added = 0
    for file in files_to_add:
        if file and os.path.exists(file):
            try:
                print(f"committing: {file}", flush=True)
                _run_git_cmd(f"git add {file}")
                n_added += 1
            except Exception as e:
                print(e)

    if n_added > 0:
        try:
            _run_git_cmd(f'git commit -am "Update Graph {BUILD_URL}"')
        except Exception as e:
            print(e)

        # make sure the graph can load, if not we will error
        try:
            gx = load_graph()
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
                if num_try == 9:
                    print(
                        "\n\n>>>>>>>>>>>> git unshallow for try %d\n\n" % num_try,
                        flush=True,
                    )
                    _run_git_cmd("git fetch --unshallow")
                print("\n\n>>>>>>>>>>>> git pull try %d\n\n" % num_try, flush=True)
                _run_git_cmd("git pull -s recursive -X theirs")
            except Exception as e:
                print(
                    "\n\n>>>>>>>>>>>> git pull try %d failed: %s \n\n" % (num_try, e),
                    flush=True,
                )
                pass
            print("\n\n>>>>>>>>>>>> git push try %d\n\n" % num_try, flush=True)
            with sensitive_env() as env:
                status = doctr_run(
                    [
                        "git",
                        "push",
                        "https://{token}@github.com/{deploy_repo}.git".format(
                            token=env.get("PASSWORD", ""),
                            deploy_repo="regro/cf-graph-countyfair",
                        ),
                        "master",
                    ],
                    token=env.get("PASSWORD", "").encode("utf-8"),
                )
            num_try += 1

        if status != 0 or not graph_ok:
            print("\n\n>>>>>>>>>>>> failed deploy - pushing to branch\n\n", flush=True)
            if not graph_ok:
                print("\n\n>>>>>>>>>>>> git unshallow graph bad\n\n", flush=True)
                _run_git_cmd("git fetch --unshallow")
            _branch = "failed-circle-run-%s" % os.environ["CIRCLE_BUILD_NUM"]
            _run_git_cmd(f"git checkout -b {_branch}")
            _run_git_cmd("git commit --allow-empty -am 'help me!'")

            with sensitive_env() as env:
                status = doctr_run(
                    [
                        "git",
                        "push",
                        "--set-upstream",
                        "https://{token}@github.com/{deploy_repo}.git".format(
                            token=env.get("PASSWORD", ""),
                            deploy_repo="regro/cf-graph-countyfair",
                        ),
                        _branch,
                    ],
                    token=env.get("PASSWORD", "").encode("utf-8"),
                )

            raise RuntimeError("bot did not push its data! stopping!")
    else:
        print("no files to commit!", flush=True)


def main(*args, **kwargs):
    parser = argparse.ArgumentParser("a tool to help update feedstocks.")
    parser.add_argument("--run")
    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        default=False,
        help=(
            "Runs in debug mode, running parallel parts "
            "sequentially and printing more info."
        ),
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Don't push changes to PRs or graph to Github",
    )
    parser.add_argument(
        "--cf-graph",
        dest="cf_graph",
        default=".",
        help="location of the graph",
    )
    args = parser.parse_args()

    if args.debug:
        os.environ["CONDA_FORGE_TICK_DEBUG"] = "1"

    script = int(args.run)
    if script in INT_SCRIPT_DICT or script == -1:
        start = time.time()
        if script == -1:
            deploy(args)
        else:
            script_md = INT_SCRIPT_DICT[script]
            func = getattr(
                importlib.import_module(f"conda_forge_tick.{script_md['module']}"),
                script_md["func"],
            )
            func(args)

        print("FINISHED STAGE {} IN {} SECONDS".format(script, time.time() - start))

    else:
        raise RuntimeError("Unknown script number")
