from unittest import mock
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from conda_forge_tick.cli import main
from conda_forge_tick.cli_context import CliContext

commands = (
    "auto-tick",
    "backup-lazy-json",
    "cache-lazy-json-to-disk",
    "deploy-to-github",
    "gather-all-feedstocks",
    "make-graph",
    "make-mappings",
    "make-migrators",
    "make-status-report",
    "sync-lazy-json-across-backends",
    "update-prs",
    "update-upstream-versions",
)

job_commands = (
    "make-graph",
    "update-prs",
    "update-upstream-versions",
)

global_options = (
    "--debug",
    "--no-debug",
    "--dry-run",
    "--no-dry-run",
    "--help",
)


def test_main_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0

    for command in commands:
        assert command in result.output

    for option in global_options:
        assert option in result.output


@pytest.mark.parametrize("command", commands)
def test_subcommand_help(command):
    runner = CliRunner()
    result = runner.invoke(main, [command, "--help"])
    assert result.exit_code == 0

    if command in job_commands:
        assert "--job" in result.output
        assert "--n-jobs" in result.output
    else:
        assert "--job" not in result.output
        assert "--n-jobs" not in result.output


@pytest.mark.parametrize("command", job_commands)
@pytest.mark.parametrize("job,n_jobs", [(0, 10), (-1, 10), (11, 10), (0, 0)])
def test_invalid_job(command: str, job: int, n_jobs: int):
    runner = CliRunner()
    result = runner.invoke(main, [command, f"--job={job}", f"--n-jobs={n_jobs}"])
    assert result.exit_code == 2
    assert "in the range" in result.output


takes_context_commands = (
    "make-graph",
    "update-upstream-versions",
    "auto-tick",
    "update-prs",
    "deploy-to-github",
    "backup-lazy-json",
    "sync-lazy-json-across-backends",
    "cache-lazy-json-to-disk",
    "make-migrators",
)


@pytest.mark.parametrize("debug", [True, False])
@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize(
    "command, patch_function",
    [
        ("gather-all-feedstocks", "conda_forge_tick.all_feedstocks.main"),
        ("make-graph", "conda_forge_tick.make_graph.main"),
        (
            "update-upstream-versions",
            "conda_forge_tick.update_upstream_versions.main",
        ),
        ("auto-tick", "conda_forge_tick.auto_tick.main"),
        ("make-status-report", "conda_forge_tick.status_report.main"),
        ("update-prs", "conda_forge_tick.update_prs.main"),
        ("make-mappings", "conda_forge_tick.mappings.main"),
        ("deploy-to-github", "conda_forge_tick.deploy.deploy"),
        ("backup-lazy-json", "conda_forge_tick.lazy_json_backups.main_backup"),
        (
            "sync-lazy-json-across-backends",
            "conda_forge_tick.lazy_json_backends.main_sync",
        ),
        (
            "cache-lazy-json-to-disk",
            "conda_forge_tick.lazy_json_backends.main_cache",
        ),
        ("make-migrators", "conda_forge_tick.make_migrators.main"),
    ],
)
def test_cli_mock_commands_pass_context(
    debug: bool,
    dry_run: bool,
    command: str,
    patch_function: str,
):
    runner = CliRunner()
    debug_flag = "--debug" if debug else "--no-debug"
    dry_run_flag = "--dry-run" if dry_run else "--no-dry-run"

    with mock.patch(patch_function) as cmd_mock:
        result = runner.invoke(main, [debug_flag, dry_run_flag, command])
        assert result.exit_code == 0
        cmd_mock.assert_called_once()

        if command not in takes_context_commands:
            for arg in cmd_mock.call_args.args:
                assert not isinstance(arg, CliContext)
            for kwarg in cmd_mock.call_args.kwargs.values():
                assert not isinstance(kwarg, CliContext)
            return

        command_context: CliContext = cmd_mock.call_args.args[0]
        assert command_context.debug is debug
        assert command_context.dry_run is dry_run


@pytest.mark.parametrize("job, n_jobs", [(1, 5), (3, 7), (4, 4)])
@pytest.mark.parametrize("package", ["foo", "bar", "baz"])
@mock.patch("conda_forge_tick.update_upstream_versions.main")
def test_cli_mock_update_upstream_versions(
    cmd_mock: MagicMock, job: int, n_jobs: int, package: str
):
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["update-upstream-versions", f"--job={job}", f"--n-jobs={n_jobs}", package],
    )

    assert result.exit_code == 0
    cmd_mock.assert_called_once_with(mock.ANY, job=job, n_jobs=n_jobs, package=package)


@pytest.mark.parametrize(
    "job, n_jobs, feedstock", [(1, 5, None), (3, 7, None), (4, 4, "foo")]
)
@mock.patch("conda_forge_tick.update_prs.main")
def test_cli_mock_update_prs(
    cmd_mock: MagicMock, job: int, n_jobs: int, feedstock: str | None
):
    fs = [f"--feedstock={feedstock}"] if feedstock is not None else []
    runner = CliRunner()
    result = runner.invoke(
        main, ["update-prs", f"--job={job}", f"--n-jobs={n_jobs}"] + fs
    )

    assert result.exit_code == 0
    cmd_mock.assert_called_once_with(
        mock.ANY, job=job, n_jobs=n_jobs, feedstock=feedstock
    )


@pytest.mark.parametrize(
    "migrators, expected_filter",
    [
        ([], None),
        (["python314"], ["python314"]),
        (["python314", "python315"], ["python314", "python315"]),
        (["compilers"], ["compilers"]),
    ],
)
@mock.patch("conda_forge_tick.status_report.main")
def test_cli_mock_make_status_report_with_migrators(
    cmd_mock: MagicMock, migrators: list[str], expected_filter: list[str] | None
):
    runner = CliRunner()
    args = ["make-status-report"]
    for migrator in migrators:
        args.extend(["--migrators", migrator])

    result = runner.invoke(main, args)

    assert result.exit_code == 0
    cmd_mock.assert_called_once_with(migrator_filter=expected_filter)
