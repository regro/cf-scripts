import os
import time

import click
from click import IntRange

from .cli_context import CliContext

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
@pass_context
def main(ctx: CliContext, debug: bool, dry_run: bool) -> None:
    ctx.debug = debug
    ctx.dry_run = dry_run

    if ctx.debug:
        os.environ["CONDA_FORGE_TICK_DEBUG"] = "1"


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
@pass_context
def update_upstream_versions(ctx: CliContext, job: int, n_jobs: int) -> None:
    from . import update_upstream_versions

    check_job_param_relative(job, n_jobs)

    update_upstream_versions.main(ctx, job=job, n_jobs=n_jobs)


@main.command(name="auto-tick")
@pass_context
def auto_tick(ctx: CliContext) -> None:
    from . import auto_tick

    auto_tick.main(ctx)


@main.command(name="make-status-report")
@pass_context
def make_status_report(ctx: CliContext) -> None:
    from . import status_report

    status_report.main(ctx)


@main.command(name="update-prs")
@job_option
@n_jobs_option
@pass_context
def update_prs(ctx: CliContext, job: int, n_jobs: int) -> None:
    from . import update_prs

    check_job_param_relative(job, n_jobs)

    update_prs.main(ctx, job=job, n_jobs=n_jobs)


@main.command(name="make-mappings")
@pass_context
def make_mappings(ctx: CliContext) -> None:
    from . import mappings

    mappings.main(ctx)


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
