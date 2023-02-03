import argparse
import importlib
import os
import time
import sys
import pdb
from functools import partial
from types import TracebackType
from .deploy import deploy

INT_SCRIPT_DICT = {
    # -1: {"module": __name__, "func": "deploy"},
    # 0: {"module": "all_feedstocks", "func": "main"},
    # 1: {"module": "make_graph", "func": "main"},
    # 2: {"module": "update_upstream_versions", "func": "main"},
    # 3: {"module": "auto_tick", "func": "main"},
    # 4: {"module": "status_report", "func": "main"},
    # 5: {"module": "audit", "func": "main"},
    # 6: {"module": "update_prs", "func": "main"},
    7: {"module": "mappings", "func": "main"},
}


def import_function(module_name: str, func_name: str):
    module = importlib.import_module(module_name)
    func = getattr(module, func_name)
    return func


#         func = getattr(
#             importlib.import_module(f"conda_forge_tick.{script_md['module']}"),
#             script_md["func"],
#         )
def _add_subparsers(parser: argparse.ArgumentParser):
    subparsers = parser.add_subparsers(dest="command")
    # Add all of the legacy parsing
    # subparser = subparsers.add_parser("-1", help="subcommand to deploy to github")
    # # deploy = partial(import_and_run, "conda_forge_tick.deploy", "deploy")
    # subparser.set_defaults(import_function=deploy)

    for idx, script_md in INT_SCRIPT_DICT.items():
        module_name = script_md["module"]
        import_path = f"conda_forge_tick.{module_name}"
        func_name = script_md["func"]
        subparser = subparsers.add_parser(
            str(idx),
            help=f"Subcommand to run {module_name}",
        )
        func = partial(import_function, import_path, func_name)
        subparser.set_defaults(import_function=func)
    # add the parsing for invoking by name instead of integer

    # subparser = subparsers.add_parser(
    #     "deploy",
    #     help="subcommand to deploy to github. Previously invoked with `conda-forge-tick -1`",
    # )
    # subparser.set_defaults(import_function=deploy)

    for idx, script_md in INT_SCRIPT_DICT.items():
        module_name = script_md["module"]
        import_path = f"conda_forge_tick.{module_name}"
        func_name = script_md["func"]
        subparser = subparsers.add_parser(
            module_name,
            help=f"Previously invoked with `conda-forge-tick {idx}`",
        )
        func = partial(import_function, import_path, func_name)
        subparser.set_defaults(import_function=func)


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
    parser.add_argument(
        "--pdb",
        default=False,
        action="store_true",
        help="Drop into a debugger on client-side exception",
    )
    _add_subparsers(parser)
    args = parser.parse_args()

    if args.debug:
        os.environ["CONDA_FORGE_TICK_DEBUG"] = "1"

    # set the pdb_hook as the except hook for all exceptions
    if args.pdb:

        def pdb_hook(
            exctype: type[BaseException],
            value: BaseException,
            traceback: TracebackType | None,
        ):
            pdb.post_mortem(traceback)

        sys.excepthook = pdb_hook

    print(f"{args=}")
    if args.import_function:
        start = time.time()
        func = args.import_function()
        func(args)
        print(f"FINISHED STAGE {args.command} IN {time.time() - start} SECONDS")

    # # legacy invocation mode below here
    # script = int(args.run)
    # if script in INT_SCRIPT_DICT or script == -1:
    #     start = time.time()
    #     if script == -1:
    #         deploy(dry_run=args.dry_run)
    #     else:
    #         script_md = INT_SCRIPT_DICT[script]
    #         func = getattr(
    #             importlib.import_module(f"conda_forge_tick.{script_md['module']}"),
    #             script_md["func"],
    #         )
    #         func(args)

    #     print(f"FINISHED STAGE {script} IN {time.time() - start} SECONDS")

    # else:
    #     raise RuntimeError("Unknown script number")
