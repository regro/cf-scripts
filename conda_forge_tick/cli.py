import argparse
import time
import os
import subprocess

from doctr.travis import run_command_hiding_token as doctr_run

from .utils import load_graph

from .all_feedstocks import main as main_all_feedstocks
from .make_graph import main as main_make_graph
from .update_upstream_versions import main as main_update_upstream_versions
from .auto_tick import main as main_auto_tick
from .status_report import main as main_status_report
from .audit import main as main_audit
from .update_prs import main as main_update_prs
from .mappings import main as main_mappings

INT_SCRIPT_DICT = {
    0: main_all_feedstocks,
    1: main_make_graph,
    2: main_update_upstream_versions,
    3: main_auto_tick,
    4: main_status_report,
    5: main_audit,
    6: main_update_prs,
    7: main_mappings,
}


def _run_git_cmd(cmd):
    return subprocess.run(cmd, shell=True, check=True)


def deploy(args):
    """Deploy the graph to github"""
    if args.dry_run:
        print("(dry run) deploying")
        return

    CIRCLE_BUILD_URL = os.environ.get("CIRCLE_BUILD_URL", "")
    for cmd in (
        ["git pull -s recursive -X theirs"]
        + [
            "git add " + v
            for v in [
                "pr_json/*",
                "status/*",
                "node_attrs/*",
                "audits/*",
                "audits/grayskull/*",
                "audits/depfinder/*",
                "versions/*",
                "profiler/*",
                "mappings/*",
                "mappings/pypi/*",
            ]
        ]
        + [f'git commit -am "Update Graph {CIRCLE_BUILD_URL}"'],
    ):
        try:
            _run_git_cmd(cmd)
        except Exception as e:
            print(e)

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
        status = doctr_run(
            [
                "git",
                "push",
                "https://{token}@github.com/{deploy_repo}.git".format(
                    token=os.environ.get("PASSWORD", ""),
                    deploy_repo="regro/cf-graph-countyfair",
                ),
                "master",
            ],
            token=os.environ.get("PASSWORD", "").encode("utf-8"),
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

        status = doctr_run(
            [
                "git",
                "push",
                "--set-upstream",
                "https://{token}@github.com/{deploy_repo}.git".format(
                    token=os.environ.get("PASSWORD", ""),
                    deploy_repo="regro/cf-graph-countyfair",
                ),
                _branch,
            ],
            token=os.environ.get("PASSWORD", "").encode("utf-8"),
        )

        raise RuntimeError("bot did not push its data! stopping!")


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

    os.environ["CONDA_FORGE_TICK_DEBUG"] = args.debug

    script = int(args.run)
    if script in INT_SCRIPT_DICT or script == -1:
        start = time.time()
        if script == -1:
            deploy(args)
        else:
            INT_SCRIPT_DICT[script](args)
        print("FINISHED STAGE {} IN {} SECONDS".format(script, time.time() - start))

    else:
        raise RuntimeError("Unknown script number")
