import logging
import os
import typing

from .make_graph import close_labels, update_graph_pr_status
from .utils import (
    setup_logger,
    load_graph,
    dump_graph,
)

if typing.TYPE_CHECKING:
    from .cli import CLIArgs

logger = logging.getLogger("conda_forge_tick.update_prs")


def main(args: "CLIArgs") -> None:
    setup_logger(logger)

    if os.path.exists("graph.json"):
        gx = load_graph()
    else:
        gx = None
    # Utility flag for testing -- we don't need to always update GH
    no_github_fetch = os.environ.get("CONDA_FORGE_TICK_NO_GITHUB_REQUESTS")
    if not no_github_fetch:
        gx = close_labels(gx, args.dry_run)
        gx = update_graph_pr_status(gx, args.dry_run)

    logger.info("writing out file")
    dump_graph(gx)


if __name__ == "__main__":
    pass
    # main()
