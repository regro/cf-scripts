import logging
import time
from typing import Optional

import click
from click import Context, IntRange

from conda_forge_tick import lazy_json_backends
from conda_forge_tick.os_utils import override_env
from conda_forge_tick.utils import setup_logging

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
    help="online: Make requests to GitHub for accessing the dependency graph. This is useful for local testing. Note "
    "however that any write operations will not be performed. Important: The current working directory will be "
    "used to cache JSON files. Local files will be used if they exist.",
)
@click.option(
    "--no-containers",
    is_flag=True,
    help=(
        "Do not use containers for isolating recipe code from the system. "
        "Turning off containers is a potential security issue."
    ),
)
@pass_context
@click.pass_context
def main(
    click_context: Context,
    ctx: CliContext,
    debug: bool,
    dry_run: bool,
    online: bool,
    no_containers: bool,
) -> None:
    log_level = "debug" if debug else "info"
    setup_logging(log_level)

    ctx.debug = debug
    ctx.dry_run = dry_run

    if online:
        logger.info("Running in online mode")
        click_context.with_resource(
            lazy_json_backends.lazy_json_override_backends(["github"]),
        )
    if no_containers:
        logger.info("Running without containers")
        click_context.with_resource(
            override_env("CF_FEEDSTOCK_OPS_IN_CONTAINER", "true")
        )


@main.command(name="gather-all-feedstocks")
def gather_all_feedstocks() -> None:
    from . import all_feedstocks

    all_feedstocks.main()


@main.command(name="make-graph")
@job_option
@n_jobs_option
@click.option(
    "--update-nodes-and-edges",
    is_flag=True,
    help="If given, update the nodes and edges in the graph. Otherwise, only update the node attrs.",
)
@click.option(
    "--schema-migration-only",
    is_flag=True,
    help="If given, only migrate the schema of the node attrs.",
)
@pass_context
def make_graph(
    ctx: CliContext,
    job: int,
    n_jobs: int,
    update_nodes_and_edges: bool,
    schema_migration_only: bool,
) -> None:
    from . import make_graph

    check_job_param_relative(job, n_jobs)

    make_graph.main(
        ctx,
        job=job,
        n_jobs=n_jobs,
        update_nodes_and_edges=update_nodes_and_edges,
        schema_migration_only=schema_migration_only,
    )


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


@main.command(name="prep-auto-tick")
@pass_context
def prep_auto_tick(ctx: CliContext) -> None:
    from . import auto_tick

    auto_tick.main_prep(ctx)


@main.command(name="auto-tick")
@pass_context
def auto_tick(ctx: CliContext) -> None:
    from . import auto_tick

    auto_tick.main(ctx)


@main.command(name="make-status-report")
@click.option(
    "--migrators",
    multiple=True,
    help="Only generate status report for specific migrators (by name or report_name). Can be specified multiple times.",
)
def make_status_report(migrators: tuple[str, ...]) -> None:
    from . import status_report

    migrator_filter = list(migrators) if migrators else None
    status_report.main(migrator_filter=migrator_filter)


@main.command(name="update-prs")
@job_option
@n_jobs_option
@click.option(
    "--feedstock",
    default=None,
    help="Only update PRs for this specific feedstock (must end with '-feedstock' suffix)",
)
@pass_context
def update_prs(ctx: CliContext, job: int, n_jobs: int, feedstock: str | None) -> None:
    from . import update_prs

    check_job_param_relative(job, n_jobs)

    update_prs.main(ctx, job=job, n_jobs=n_jobs, feedstock=feedstock)


@main.command(name="make-mappings")
def make_mappings() -> None:
    from . import mappings

    mappings.main()


@main.command(name="deploy-to-github")
@click.option(
    "--git-only",
    is_flag=True,
    help="If given, only deploy graph data to GitHub via the git command line.",
)
@click.option(
    "--dirs-to-ignore",
    default=None,
    help=(
        "Comma-separated list of directories to ignore. If given, directories will "
        "not be deployed."
    ),
)
@click.option(
    "--dirs-to-deploy",
    default=None,
    help=(
        "Comma-separated list of directories to deplot. If given, all other "
        "directories will be ignored."
    ),
)
@pass_context
def deploy_to_github(
    ctx: CliContext, git_only: bool, dirs_to_ignore: str, dirs_to_deploy: str
) -> None:
    from . import deploy

    deploy.deploy(
        dry_run=ctx.dry_run,
        git_only=git_only,
        dirs_to_ignore=[] if dirs_to_ignore is None else dirs_to_ignore.split(","),
        dirs_to_deploy=[] if dirs_to_deploy is None else dirs_to_deploy.split(","),
    )


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


@main.command(name="make-import-to-package-mapping")
@click.option(
    "--max-artifacts",
    default=30000,
    type=IntRange(1, None),
    show_default=True,
    help="If given, the maximum number of artifacts to process.",
)
@pass_context
def make_import_to_package_mapping(
    ctx: CliContext,
    max_artifacts: int,
) -> None:
    """Make the import to package mapping."""
    from . import import_to_pkg

    import_to_pkg.main(ctx, max_artifacts)


@main.command(name="make-migrators")
@pass_context
def make_migrators(
    ctx: CliContext,
) -> None:
    """Make the migrators."""
    from . import make_migrators as _make_migrators

    _make_migrators.main(ctx)


@main.command(name="react-to-event")
@click.option(
    "--event",
    required=True,
    help="The event to react to.",
    type=click.Choice(["pr", "push"]),
)
@click.option(
    "--uid",
    required=True,
    help=(
        "The unique identifier of the event. It is the PR "
        "id for PR events or the feedstock name for push events"
    ),
    type=str,
)
@pass_context
def react_to_event(
    ctx: CliContext,
    event: str,
    uid: str,
) -> None:
    """React to an event."""
    from .events import react_to_event

    react_to_event(ctx, event, uid)


@main.command(name="clean-disk-space")
@click.option("--ci-service", required=True, type=click.Choice(["github-actions"]))
def clean_disk_space(ci_service) -> None:
    """Clean up disk space on CI services."""
    from .os_utils import clean_disk_space

    clean_disk_space(ci_service)


if __name__ == "__main__":
    # This entrypoint can be used for debugging.
    # click will read the command line arguments and call the corresponding
    # function.
    # Example: python -m conda_forge_tick.cli --debug make-graph
    main()
