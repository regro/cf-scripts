import argparse
import importlib
import os
import time

from .deploy import deploy

SCRIPT_DICT = {
    "gather-all-feedstocks": {"module": "all_feedstocks", "func": "main"},
    "make-graph": {"module": "make_graph", "func": "main"},
    "update-upstream-versions": {"module": "update_upstream_versions", "func": "main"},
    "auto-tick": {"module": "auto_tick", "func": "main"},
    "make-status-report": {"module": "status_report", "func": "main"},
    "update-prs": {"module": "update_prs", "func": "main"},
    "make-mappings": {"module": "mappings", "func": "main"},
    "deploy-to-github": None,
}


def main(*args, **kwargs):
    parser = argparse.ArgumentParser("a tool to help update feedstocks.")
    parser.add_argument("step", choices=list(SCRIPT_DICT.keys()))
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
    parser.add_argument(
        "--job",
        default=1,
        type=int,
        help=(
            "If given with --n-jobs, the number of the job to "
            "run in the range [1, n_jobs]."
        ),
    )
    parser.add_argument(
        "--n-jobs",
        default=1,
        type=int,
        help=("If given, the total number of jobs being run."),
    )
    args = parser.parse_args()

    if args.debug:
        os.environ["CONDA_FORGE_TICK_DEBUG"] = "1"

    script = args.step
    if script in SCRIPT_DICT:
        start = time.time()
        if script == "deploy-github":
            deploy(dry_run=args.dry_run)
        else:
            script_md = SCRIPT_DICT[script]
            func = getattr(
                importlib.import_module(f"conda_forge_tick.{script_md['module']}"),
                script_md["func"],
            )
            func(args)

        print(f"FINISHED STAGE {script} IN {time.time() - start} SECONDS")

    else:
        raise RuntimeError("Unknown step!")
