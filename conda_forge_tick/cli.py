import logging
import os
import time
from typing import Optional

import click
from click import IntRange

from conda_forge_tick import lazy_json_backends
from conda_forge_tick.utils import setup_logger

from .cli_context import CliContext

logger = logging.getLogger(__name__)

pass_context = click.make_pass_decorator(CliContext, ensure=True)
job_option = click.option(
    "--job",
    default=1,
    type=IntRange(1, None),
    show_default=True,
    help="If given with --n-jobs, the number of the job to run in the range [1, n_jobs].",
)
n_jobs_option = click.option(
    "--n-jobs",
    default=1,
    type=IntRange(1, None),
    show_default=True,
    help="If given, the total number of jobs being run.",
)


def check_job_param_relative(job: int, n_jobs: int) -> None:
    if job > n_jobs:
        raise click.BadParameter(f"job must be in the range [1, n_jobs], got {job}")


class TimedCommand(click.Command):
    def invoke(self, ctx: click.Context):
        start = time.time()
        super().invoke(ctx)
        click.echo(f"FINISHED STAGE {self.name} IN {time.time() - start} SECONDS")


click.Group.command_class = TimedCommand


@click.group()
@click.option("--debug/--no-debug", default=False)
@click.option(
    "--dry-run/--no-dry-run",
    default=False,
    help="dry run: don't push changes to PRs or graph to Github",
)
@click.option(
    "--online/--offline",
    default=False,
    help="Online: Use the GitHub API for accessing the dependency graph. This is useful for local testing. Note "
    "however that any write operations will not be performed.",
)
@pass_context
def main(ctx: CliContext, debug: bool, dry_run: bool, online: bool) -> None:
    log_level = "debug" if debug else "info"
    setup_logger(logger, log_level)

    ctx.debug = debug
    ctx.dry_run = dry_run

    if ctx.debug:
        os.environ["CONDA_FORGE_TICK_DEBUG"] = "1"

    if online:
        logger.info("Running in online mode")
        lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = ("github",)
        lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = "github"


@main.command(name="gather-all-feedstocks")
@pass_context
def gather_all_feedstocks(ctx: CliContext) -> None:
    from . import all_feedstocks

    all_feedstocks.main(ctx)


@main.command(name="make-graph")
@pass_context
def make_graph(ctx: CliContext) -> None:
    from . import make_graph

    make_graph.main(ctx)


@main.command(name="update-upstream-versions")
@job_option
@n_jobs_option
@click.argument(
    "package",
    required=False,
)
@pass_context
def update_upstream_versions(
    ctx: CliContext, job: int, n_jobs: int, package: Optional[str]
) -> None:
    """
    Update the upstream versions of feedstocks in the graph.

    If PACKAGE is given, only update that package, otherwise update all packages.
    """
    from . import update_upstream_versions

    check_job_param_relative(job, n_jobs)

    update_upstream_versions.main(ctx, job=job, n_jobs=n_jobs, package=package)


@main.command(name="auto-tick")
@pass_context
def auto_tick(ctx: CliContext) -> None:
    from . import auto_tick

    auto_tick.main(ctx)


@main.command(name="make-status-report")
def make_status_report() -> None:
    from . import status_report

    status_report.main()


@main.command(name="update-prs")
@job_option
@n_jobs_option
@pass_context
def update_prs(ctx: CliContext, job: int, n_jobs: int) -> None:
    from . import update_prs

    check_job_param_relative(job, n_jobs)

    update_prs.main(ctx, job=job, n_jobs=n_jobs)


@main.command(name="make-mappings")
def make_mappings() -> None:
    from . import mappings

    mappings.main()


@main.command(name="deploy-to-github")
@pass_context
def deploy_to_github(ctx: CliContext) -> None:
    from . import deploy

    deploy.deploy(ctx)


@main.command(name="backup-lazy-json")
@pass_context
def backup_lazy_json(ctx: CliContext) -> None:
    from . import lazy_json_backups

    lazy_json_backups.main_backup(ctx)


@main.command(name="sync-lazy-json-across-backends")
@pass_context
def sync_lazy_json_across_backends(ctx: CliContext) -> None:
    from . import lazy_json_backends

    lazy_json_backends.main_sync(ctx)


@main.command(name="cache-lazy-json-to-disk")
@pass_context
def cache_lazy_json_to_disk(ctx: CliContext) -> None:
    from . import lazy_json_backends

    lazy_json_backends.main_cache(ctx)


if __name__ == "__main__":
    # This entrypoint can be used for debugging.
    # click will read the command line arguments and call the corresponding
    # function.
    # Example: python -m conda_forge_tick.cli --debug make-graph
    main()
