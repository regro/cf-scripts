import argparse
import importlib
import os
import time

from .deploy import deploy

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
            deploy(dry_run=args.dry_run)
        else:
            script_md = INT_SCRIPT_DICT[script]
            func = getattr(
                importlib.import_module(f"conda_forge_tick.{script_md['module']}"),
                script_md["func"],
            )
            func(args)

        print(f"FINISHED STAGE {script} IN {time.time() - start} SECONDS")

    else:
        raise RuntimeError("Unknown script number")
