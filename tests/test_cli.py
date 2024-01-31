import pytest
from click.testing import CliRunner

from conda_forge_tick.cli import main

commands = (
    "auto-tick",
    "backup-lazy-json",
    "cache-lazy-json-to-disk",
    "deploy-to-github",
    "gather-all-feedstocks",
    "make-graph",
    "make-mappings",
    "make-status-report",
    "sync-lazy-json-across-backends",
    "update-prs",
    "update-upstream-versions",
)

job_commands = (
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
