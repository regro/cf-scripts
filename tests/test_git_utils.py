import base64
import datetime
import json
import logging
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import github3.exceptions
import pytest
import requests
from requests.structures import CaseInsensitiveDict

import conda_forge_tick
from conda_forge_tick.git_utils import (
    Bound,
    DryRunBackend,
    DuplicatePullRequestError,
    GitCli,
    GitCliError,
    GitConnectionMode,
    GitHubBackend,
    GitPlatformBackend,
    GitPlatformError,
    RepositoryNotFoundError,
    _get_pth_blob_sha_and_content,
    delete_file_via_gh_api,
    github_client,
    push_file_via_gh_api,
    trim_pr_json_keys,
)
from conda_forge_tick.models.pr_json import (
    GithubPullRequestMergeableState,
    PullRequestState,
)
from conda_forge_tick.os_utils import pushd

"""
Note: You have to have git installed on your machine to run these tests.
"""


@mock.patch("subprocess.run")
@pytest.mark.parametrize("check_error", [True, False])
def test_git_cli_run_git_command_no_error(
    subprocess_run_mock: MagicMock, check_error: bool, tmp_path: Path
):
    cli = GitCli()

    working_directory = tmp_path

    cli._run_git_command(
        ["GIT_COMMAND", "ARG1", "ARG2"], working_directory, check_error
    )

    subprocess_run_mock.assert_called_once_with(
        ["git", "GIT_COMMAND", "ARG1", "ARG2"],
        check=check_error,
        cwd=working_directory,
        stdout=subprocess.PIPE,
        stderr=None,
        text=True,
    )


@mock.patch("subprocess.run")
def test_git_cli_run_git_command_error(subprocess_run_mock: MagicMock, tmp_path: Path):
    cli = GitCli()

    working_directory = tmp_path

    subprocess_run_mock.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd=""
    )

    with pytest.raises(GitCliError):
        cli._run_git_command(["GIT_COMMAND"], working_directory)


@pytest.mark.parametrize("suppress_all_output", [True, False])
@pytest.mark.parametrize("check_error", [True, False])
@mock.patch("subprocess.run")
def test_git_cli_run_git_command_mock(
    subprocess_run_mock: MagicMock,
    check_error: bool,
    suppress_all_output: bool,
    tmp_path: Path,
):
    """Check if all parameters are passed correctly to the subprocess.run function."""
    cli = GitCli()

    working_directory = tmp_path

    cli._run_git_command(
        ["COMMAND", "ARG1", "ARG2"], working_directory, check_error, suppress_all_output
    )

    subprocess_run_mock.assert_called_once_with(
        ["git", "COMMAND", "ARG1", "ARG2"],
        check=check_error,
        cwd=working_directory,
        stdout=subprocess.PIPE if not suppress_all_output else subprocess.DEVNULL,
        stderr=None if not suppress_all_output else subprocess.DEVNULL,
        text=True,
    )


@pytest.mark.parametrize("check_error", [True, False])
def test_git_cli_run_git_command_stdout_captured(capfd, check_error: bool):
    """Verify that the stdout of the git command is captured and not printed to the console."""
    cli = GitCli()

    p = cli._run_git_command(["version"], check_error=check_error)

    captured = capfd.readouterr()

    assert captured.out == ""
    assert p.stdout.startswith("git version")


def test_git_cli_run_git_command_stderr_not_captured(capfd):
    """Verify that the stderr of the git command is not captured if no token is hidden."""
    cli = GitCli()

    p = cli._run_git_command(["non-existing-command"], check_error=False)

    captured = capfd.readouterr()

    assert captured.out == ""
    assert "command" in captured.err
    assert p.stderr is None


def test_git_cli_outside_repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        with dir_path.joinpath("test.txt").open("w") as f:
            f.write("Hello, World!")

        cli = GitCli()

        with pytest.raises(GitCliError):
            cli._run_git_command(["status"], working_directory=dir_path)

        with pytest.raises(GitCliError):
            cli.reset_hard(dir_path)

        with pytest.raises(GitCliError):
            cli.add_remote(dir_path, "origin", "https://github.com/torvalds/linux.git")

        with pytest.raises(GitCliError):
            cli.fetch_all(dir_path)

        assert not cli.does_branch_exist(dir_path, "main")

        with pytest.raises(GitCliError):
            cli.checkout_branch(dir_path, "main")


# noinspection PyProtectedMember
def init_temp_git_repo(git_dir: Path, bare: bool = False):
    cli = GitCli()
    bare_arg = ["--bare"] if bare else []
    cli._run_git_command(["init", *bare_arg, "-b", "main"], working_directory=git_dir)
    cli._run_git_command(
        ["config", "user.name", "CI Test User"], working_directory=git_dir
    )
    cli._run_git_command(
        ["config", "user.email", "ci-test-user-invalid@example.com"],
        working_directory=git_dir,
    )


@pytest.mark.parametrize(
    "n_paths,all_", [(0, True), (1, False), (1, True), (2, False), (2, True)]
)
@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_add_success_mock(
    run_git_command_mock: MagicMock, n_paths: int, all_: bool, tmp_path: Path
):
    cli = GitCli()

    git_dir = tmp_path
    paths = [Path(f"test{i}.txt") for i in range(n_paths)]

    cli.add(git_dir, *paths, all_=all_)

    expected_all_arg = ["--all"] if all_ else []

    run_git_command_mock.assert_called_once_with(
        ["add", *expected_all_arg, *paths], git_dir
    )


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_add_no_arguments_error(
    run_git_command_mock: MagicMock, tmp_path: Path
):
    cli = GitCli()

    git_dir = tmp_path

    with pytest.raises(ValueError, match="Either pathspec or all_ must be set"):
        cli.add(git_dir)

    run_git_command_mock.assert_not_called()


@pytest.mark.parametrize(
    "n_paths,all_", [(0, True), (1, False), (1, True), (2, False), (2, True)]
)
def test_git_cli_add_success(n_paths: int, all_: bool):
    with tempfile.TemporaryDirectory() as tmp_dir:
        git_dir = Path(tmp_dir)
        init_temp_git_repo(git_dir)

        pathspec = [git_dir / f"test{i}.txt" for i in range(n_paths)]

        for path in pathspec + [git_dir / "all_tracker.txt"]:
            path.touch()

        cli = GitCli()
        cli.add(git_dir, *pathspec, all_=all_)

        tracked_files = cli._run_git_command(
            ["ls-files", "-s"],
            git_dir,
        ).stdout

        for path in pathspec:
            assert path.name in tracked_files

        if all_ and n_paths == 0:
            # note that n_paths has to be zero to add unknown files to the working tree
            assert "all_tracker.txt" in tracked_files
        else:
            assert "all_tracker.txt" not in tracked_files


@pytest.mark.parametrize("allow_empty", [True, False])
@pytest.mark.parametrize("all_", [True, False])
@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_commit_success_mock(
    run_git_command_mock: MagicMock, all_: bool, allow_empty: bool, tmp_path: Path
):
    git_dir = tmp_path
    message = "COMMIT_MESSAGE"

    cli = GitCli()
    cli.commit(git_dir, message, all_, allow_empty)

    expected_all_arg = ["-a"] if all_ else []
    expected_allow_empty_arg = ["--allow-empty"] if allow_empty else []

    run_git_command_mock.assert_called_once_with(
        ["commit", *expected_all_arg, *expected_allow_empty_arg, "-m", message], git_dir
    )


@pytest.mark.parametrize("allow_empty", [True, False])
@pytest.mark.parametrize("empty", [True, False])
@pytest.mark.parametrize("all_", [True, False])
def test_git_cli_commit(all_: bool, empty: bool, allow_empty: bool):
    with tempfile.TemporaryDirectory() as tmp_dir:
        git_dir = Path(tmp_dir)
        init_temp_git_repo(git_dir)

        cli = GitCli()

        test_file = git_dir.joinpath("test.txt")
        with test_file.open("w") as f:
            f.write("Hello, World!")
        cli.add(git_dir, git_dir / "test.txt")
        cli.commit(git_dir, "Add Test")

        if not empty:
            test_file.unlink()
            if not all_:
                cli.add(git_dir, git_dir / "test.txt")

        if empty and not allow_empty:
            with pytest.raises(GitCliError):
                cli.commit(git_dir, "Add Test", all_, allow_empty)
            return

        cli.commit(git_dir, "Add Test", all_, allow_empty)

        git_log = cli._run_git_command(["log"], git_dir).stdout

        assert "Add Test" in git_log


def test_git_cli_reset_hard_already_reset():
    cli = GitCli()
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        init_temp_git_repo(dir_path)
        cli._run_git_command(
            ["commit", "--allow-empty", "-m", "First commit"],
            working_directory=dir_path,
        )

        cli._run_git_command(
            ["commit", "--allow-empty", "-m", "Second commit"],
            working_directory=dir_path,
        )

        cli.reset_hard(dir_path)

        git_log = subprocess.run(
            "git log", cwd=dir_path, shell=True, capture_output=True
        ).stdout.decode()

        assert "First commit" in git_log
        assert "Second commit" in git_log


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_reset_hard_mock(run_git_command_mock: MagicMock, tmp_path: Path):
    cli = GitCli()

    git_dir = tmp_path

    cli.reset_hard(git_dir)

    run_git_command_mock.assert_called_once_with(
        ["reset", "--quiet", "--hard", "HEAD"], git_dir
    )


def test_git_cli_reset_hard():
    cli = GitCli()
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        init_temp_git_repo(dir_path)
        cli._run_git_command(
            ["commit", "--allow-empty", "-m", "Initial commit"],
            working_directory=dir_path,
        )

        with dir_path.joinpath("test.txt").open("w") as f:
            f.write("Hello, World!")

        cli._run_git_command(["add", "test.txt"], working_directory=dir_path)
        cli._run_git_command(
            ["commit", "-am", "Add test.txt"], working_directory=dir_path
        )

        with dir_path.joinpath("test.txt").open("w") as f:
            f.write("Hello, World! Again!")

        cli.reset_hard(dir_path)

        with dir_path.joinpath("test.txt").open("r") as f:
            assert f.read() == "Hello, World!"


def test_git_cli_clone_repo_not_exists():
    cli = GitCli()

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        with pytest.raises(GitCliError):
            cli.clone_repo(
                "https://github.com/conda-forge/this-repo-does-not-exist.git", dir_path
            )


def test_git_cli_clone_repo_success():
    cli = GitCli()

    git_url = "https://github.com/conda-forge/duckdb-feedstock.git"

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir) / "duckdb-feedstock"

        # this is an archived feedstock that should not change
        cli.clone_repo(git_url, dir_path)

        readme_file = dir_path.joinpath("README.md")

        assert readme_file.exists()


def test_git_cli_clone_repo_existing_empty_dir():
    cli = GitCli()

    git_url = "https://github.com/conda-forge/duckdb-feedstock.git"

    with tempfile.TemporaryDirectory() as tmpdir:
        target = Path(tmpdir) / "duckdb-feedstock"

        target.mkdir()

        cli.clone_repo(git_url, target)

        readme_file = target.joinpath("README.md")

        assert readme_file.exists()


@mock.patch("conda_forge_tick.git_utils.GitCli.reset_hard")
@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_clone_repo_mock_success(
    run_git_command_mock: MagicMock, reset_hard_mock: MagicMock
):
    cli = GitCli()

    git_url = "https://git-repository.com/repo.git"

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir) / "repo"

        cli.clone_repo(git_url, dir_path)

        run_git_command_mock.assert_called_once_with(
            ["clone", "--quiet", git_url, dir_path]
        )


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_clone_repo_mock_error(run_git_command_mock: MagicMock):
    cli = GitCli()

    git_url = "https://git-repository.com/repo.git"

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir) / "repo"

        run_git_command_mock.side_effect = GitCliError("Error")

        with pytest.raises(GitCliError, match="Error cloning repository"):
            cli.clone_repo(git_url, dir_path)


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_add_remote_mock(run_git_command_mock: MagicMock, tmp_path: Path):
    cli = GitCli()

    git_dir = tmp_path
    remote_name = "origin"
    remote_url = "https://git-repository.com/repo.git"

    cli.add_remote(git_dir, remote_name, remote_url)

    run_git_command_mock.assert_called_once_with(
        ["remote", "add", remote_name, remote_url], git_dir
    )


def test_git_cli_add_remote():
    cli = GitCli()

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        init_temp_git_repo(dir_path)

        remote_name = "remote24"
        remote_url = "https://git-repository.com/repo.git"

        cli.add_remote(dir_path, remote_name, remote_url)

        output = subprocess.run(
            "git remote -v", cwd=dir_path, shell=True, capture_output=True
        )

        assert remote_name in output.stdout.decode()
        assert remote_url in output.stdout.decode()


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_push_to_url_mock(run_git_command_mock: MagicMock, tmp_path: Path):
    cli = GitCli()

    git_dir = tmp_path
    remote_url = "https://git-repository.com/repo.git"

    cli.push_to_url(git_dir, remote_url, "BRANCH_NAME")

    run_git_command_mock.assert_called_once_with(
        ["push", remote_url, "BRANCH_NAME"], git_dir
    )


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_push_to_url_mock_error(
    run_git_command_mock: MagicMock, tmp_path: Path
):
    cli = GitCli()

    run_git_command_mock.side_effect = GitCliError("Error")

    with pytest.raises(GitCliError):
        cli.push_to_url(tmp_path, "https://git-repository.com/repo.git", "BRANCH_NAME")


def test_git_cli_push_to_url_local_repository():
    cli = GitCli()

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        source_repo = dir_path / "source_repo"
        source_repo.mkdir()
        init_temp_git_repo(source_repo, bare=True)

        local_repo = dir_path / "local_repo"
        local_repo.mkdir()
        cli._run_git_command(["clone", source_repo.resolve(), local_repo])

        # remove all references to the original repo
        cli._run_git_command(
            ["remote", "remove", "origin"], working_directory=local_repo
        )

        with local_repo.joinpath("test.txt").open("w") as f:
            f.write("Hello, World!")

        cli._run_git_command(["add", "test.txt"], working_directory=local_repo)
        cli._run_git_command(
            ["commit", "-am", "Add test.txt"], working_directory=local_repo
        )

        cli.push_to_url(local_repo, str(source_repo.resolve()), "main")

        source_git_log = subprocess.run(
            "git log", cwd=source_repo, shell=True, capture_output=True
        ).stdout.decode()

        assert "test.txt" in source_git_log


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_add_token_mock(run_git_command_mock: MagicMock, tmp_path: Path):
    cli = GitCli()

    git_dir = tmp_path

    origin = "https://git-repository.com"
    token = "TOKEN"

    cli.add_token(git_dir, origin, token)

    http_basic_token = base64.b64encode(f"x-access-token:{token}".encode()).decode()

    run_git_command_mock.assert_called_once_with(
        [
            "config",
            "--local",
            "http.https://git-repository.com/.extraheader",
            f"AUTHORIZATION: basic {http_basic_token}",
        ],
        git_dir,
        suppress_all_output=True,
    )


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_clear_token_mock(run_git_command_mock: MagicMock, tmp_path: Path):
    cli = GitCli()

    git_dir = tmp_path

    origin = "https://git-repository.com"

    cli.clear_token(git_dir, origin)

    run_git_command_mock.assert_called_once_with(
        [
            "config",
            "--local",
            "--unset",
            "http.https://git-repository.com/.extraheader",
        ],
        git_dir,
    )


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_fetch_all_mock(run_git_command_mock: MagicMock, tmp_path: Path):
    cli = GitCli()

    git_dir = tmp_path

    cli.fetch_all(git_dir)

    run_git_command_mock.assert_called_once_with(["fetch", "--all", "--quiet"], git_dir)


def test_git_cli_fetch_all():
    cli = GitCli()

    git_url = "https://github.com/conda-forge/duckdb-feedstock.git"

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir) / "duckdb-feedstock"

        cli.clone_repo(git_url, dir_path)
        cli.fetch_all(dir_path)


def test_git_cli_does_branch_exist():
    cli = GitCli()

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        init_temp_git_repo(dir_path)

        assert not cli.does_branch_exist(dir_path, "main")

        cli._run_git_command(["checkout", "-b", "main"], working_directory=dir_path)
        cli._run_git_command(
            ["commit", "--allow-empty", "-m", "Initial commit"],
            working_directory=dir_path,
        )

        assert cli.does_branch_exist(dir_path, "main")


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
@pytest.mark.parametrize("does_exist", [True, False])
def test_git_cli_does_branch_exist_mock(
    run_git_command_mock: MagicMock, does_exist: bool, tmp_path: Path
):
    cli = GitCli()

    git_dir = tmp_path
    branch_name = "main"

    run_git_command_mock.return_value = (
        subprocess.CompletedProcess(args=[], returncode=0)
        if does_exist
        else subprocess.CompletedProcess(args=[], returncode=1)
    )

    assert cli.does_branch_exist(git_dir, branch_name) is does_exist

    run_git_command_mock.assert_called_once_with(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        git_dir,
        check_error=False,
    )


def test_git_cli_does_remote_exist_false():
    cli = GitCli()

    remote_url = "https://github.com/conda-forge/this-repo-does-not-exist.git"

    assert not cli.does_remote_exist(remote_url)


def test_git_cli_does_remote_exist_true():
    cli = GitCli()

    remote_url = "https://github.com/conda-forge/pytest-feedstock.git"

    assert cli.does_remote_exist(remote_url)


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
@pytest.mark.parametrize("does_exist", [True, False])
def test_git_cli_does_remote_exist_mock(
    run_git_command_mock: MagicMock, does_exist: bool
):
    cli = GitCli()

    remote_url = "https://git-repository.com/repo.git"

    run_git_command_mock.return_value = (
        subprocess.CompletedProcess(args=[], returncode=0)
        if does_exist
        else subprocess.CompletedProcess(args=[], returncode=1)
    )

    assert cli.does_remote_exist(remote_url) is does_exist

    run_git_command_mock.assert_called_once_with(
        ["ls-remote", remote_url], check_error=False
    )


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
@pytest.mark.parametrize("track", [True, False])
def test_git_cli_checkout_branch_mock(
    run_git_command_mock: MagicMock, track: bool, tmp_path: Path
):
    branch_name = "BRANCH_NAME"

    cli = GitCli()
    git_dir = tmp_path

    cli.checkout_branch(git_dir, branch_name, track=track)

    track_flag = ["--track"] if track else []

    run_git_command_mock.assert_called_once_with(
        ["checkout", "--quiet", *track_flag, branch_name], git_dir
    )


def test_git_cli_checkout_branch_no_track():
    cli = GitCli()

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        init_temp_git_repo(dir_path)
        cli._run_git_command(["checkout", "-b", "main"], working_directory=dir_path)
        cli._run_git_command(
            ["commit", "--allow-empty", "-m", "Initial commit"],
            working_directory=dir_path,
        )

        assert (
            "main"
            in subprocess.run(
                "git status", cwd=dir_path, shell=True, capture_output=True
            ).stdout.decode()
        )

        branch_name = "new-branch-name"

        cli._run_git_command(["branch", branch_name], working_directory=dir_path)

        cli.checkout_branch(dir_path, branch_name)

        assert (
            branch_name
            in subprocess.run(
                "git status", cwd=dir_path, shell=True, capture_output=True
            ).stdout.decode()
        )


def test_git_cli_diffed_files():
    cli = GitCli()

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        init_temp_git_repo(dir_path)

        cli.commit(dir_path, "Initial commit", allow_empty=True)
        dir_path.joinpath("test.txt").touch()
        cli.add(dir_path, dir_path / "test.txt")
        cli.commit(dir_path, "Add test.txt")

        diffed_files = list(cli.diffed_files(dir_path, "HEAD~1"))

        assert (dir_path / "test.txt") in diffed_files
        assert len(diffed_files) == 1


def test_git_cli_diffed_files_no_diff():
    cli = GitCli()

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        init_temp_git_repo(dir_path)

        cli.commit(dir_path, "Initial commit", allow_empty=True)

        diffed_files = list(cli.diffed_files(dir_path, "HEAD"))

        assert len(diffed_files) == 0


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_diffed_files_mock(run_git_command_mock: MagicMock, tmp_path: Path):
    cli = GitCli()

    git_dir = tmp_path
    commit = "COMMIT"

    run_git_command_mock.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="test.txt\n"
    )

    diffed_files = list(cli.diffed_files(git_dir, commit))

    run_git_command_mock.assert_called_once_with(
        ["diff", "--name-only", "--relative", commit, "HEAD"],
        git_dir,
    )

    assert diffed_files == [git_dir / "test.txt"]


def test_git_cli_clone_fork_and_branch_minimal():
    fork_url = "https://github.com/regro-cf-autotick-bot/pytest-feedstock.git"
    upstream_url = "https://github.com/conda-forge/pytest-feedstock.git"

    cli = GitCli()

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir) / "pytest-feedstock"

        new_branch_name = "new_branch_name"

        cli.clone_fork_and_branch(fork_url, dir_path, upstream_url, new_branch_name)

        assert cli.does_branch_exist(dir_path, "main")
        assert (
            new_branch_name
            in subprocess.run(
                "git status", cwd=dir_path, shell=True, capture_output=True
            ).stdout.decode()
        )


@pytest.mark.parametrize("remote_already_exists", [True, False])
@pytest.mark.parametrize(
    "base_branch_exists,git_checkout_track_error",
    [(True, False), (False, False), (False, True)],
)
@pytest.mark.parametrize("new_branch_already_exists", [True, False])
@pytest.mark.parametrize("target_repo_already_exists", [True, False])
@mock.patch("conda_forge_tick.git_utils.GitCli.reset_hard")
@mock.patch("conda_forge_tick.git_utils.GitCli.checkout_new_branch")
@mock.patch("conda_forge_tick.git_utils.GitCli.checkout_branch")
@mock.patch("conda_forge_tick.git_utils.GitCli.does_branch_exist")
@mock.patch("conda_forge_tick.git_utils.GitCli.fetch_all")
@mock.patch("conda_forge_tick.git_utils.GitCli.add_remote")
@mock.patch("conda_forge_tick.git_utils.GitCli.clone_repo")
def test_git_cli_clone_fork_and_branch_mock(
    clone_repo_mock: MagicMock,
    add_remote_mock: MagicMock,
    fetch_all_mock: MagicMock,
    does_branch_exist_mock: MagicMock,
    checkout_branch_mock: MagicMock,
    checkout_new_branch_mock: MagicMock,
    reset_hard_mock: MagicMock,
    remote_already_exists: bool,
    base_branch_exists: bool,
    git_checkout_track_error: bool,
    new_branch_already_exists: bool,
    target_repo_already_exists: bool,
    caplog,
):
    fork_url = "https://github.com/regro-cf-autotick-bot/pytest-feedstock.git"
    upstream_url = "https://github.com/conda-forge/pytest-feedstock.git"

    caplog.set_level(logging.DEBUG)

    cli = GitCli()

    if target_repo_already_exists:
        clone_repo_mock.side_effect = GitCliError(
            "target_dir is not an empty directory"
        )

    if remote_already_exists:
        add_remote_mock.side_effect = GitCliError("Remote already exists")

    does_branch_exist_mock.return_value = base_branch_exists

    def checkout_branch_side_effect(_git_dir: Path, branch: str, track: bool = False):
        if track and git_checkout_track_error:
            raise GitCliError("Error checking out branch with --track")

        if new_branch_already_exists and branch == "new_branch_name":
            raise GitCliError("Branch new_branch_name already exists")

    checkout_branch_mock.side_effect = checkout_branch_side_effect

    with tempfile.TemporaryDirectory() as tmpdir:
        git_dir = Path(tmpdir) / "pytest-feedstock"

        if target_repo_already_exists:
            git_dir.mkdir()

        cli.clone_fork_and_branch(
            fork_url, git_dir, upstream_url, "new_branch_name", "base_branch"
        )

    clone_repo_mock.assert_called_once_with(fork_url, git_dir)
    if target_repo_already_exists:
        reset_hard_mock.assert_any_call(git_dir)

    add_remote_mock.assert_called_once_with(git_dir, "upstream", upstream_url)
    if remote_already_exists:
        assert "remote 'upstream' already exists" in caplog.text

    fetch_all_mock.assert_called_once_with(git_dir)

    if base_branch_exists:
        checkout_branch_mock.assert_any_call(git_dir, "base_branch")
    else:
        checkout_branch_mock.assert_any_call(
            git_dir, "upstream/base_branch", track=True
        )

        if git_checkout_track_error:
            assert "Could not check out with git checkout --track" in caplog.text

            checkout_new_branch_mock.assert_any_call(
                git_dir, "base_branch", start_point="upstream/base_branch"
            )

    reset_hard_mock.assert_called_with(git_dir, "upstream/base_branch")
    checkout_branch_mock.assert_any_call(git_dir, "new_branch_name")

    if not new_branch_already_exists:
        return

    assert "branch new_branch_name does not exist" in caplog.text
    checkout_new_branch_mock.assert_called_with(
        git_dir, "new_branch_name", start_point="base_branch"
    )


def test_git_cli_clone_fork_and_branch_non_existing_remote():
    origin_url = "https://github.com/conda-forge/this-repo-does-not-exist.git"
    upstream_url = "https://github.com/conda-forge/duckdb-feedstock.git"
    new_branch = "NEW_BRANCH"

    cli = GitCli()

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir) / "duckdb-feedstock"

        with pytest.raises(GitCliError, match="does the remote exist?"):
            cli.clone_fork_and_branch(origin_url, dir_path, upstream_url, new_branch)


def test_git_cli_clone_fork_and_branch_non_existing_remote_existing_target_dir(caplog):
    origin_url = "https://github.com/conda-forge/this-repo-does-not-exist.git"
    upstream_url = "https://github.com/conda-forge/duckdb-feedstock.git"
    new_branch = "NEW_BRANCH"

    cli = GitCli()
    caplog.set_level(logging.DEBUG)

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir) / "duckdb-feedstock"
        dir_path.mkdir()

        with pytest.raises(GitCliError):
            cli.clone_fork_and_branch(origin_url, dir_path, upstream_url, new_branch)

        assert "trying to reset hard" in caplog.text


@pytest.mark.parametrize(
    "backend", [GitHubBackend(MagicMock(), MagicMock(), ""), DryRunBackend()]
)
@mock.patch(
    "conda_forge_tick.git_utils.GitHubBackend.user", new_callable=mock.PropertyMock
)
@mock.patch("conda_forge_tick.git_utils.GitCli.clone_fork_and_branch")
def test_git_platform_backend_clone_fork_and_branch(
    clone_fork_and_branch_mock: MagicMock,
    user_mock: MagicMock,
    backend: GitPlatformBackend,
    tmp_path: Path,
):
    upstream_owner = "UPSTREAM-OWNER"
    repo_name = "REPO"
    target_dir = tmp_path
    new_branch = "NEW_BRANCH"
    base_branch = "BASE_BRANCH"

    user_mock.return_value = "USER"

    backend = GitHubBackend(MagicMock(), MagicMock(), "")
    backend.clone_fork_and_branch(
        upstream_owner, repo_name, target_dir, new_branch, base_branch
    )

    clone_fork_and_branch_mock.assert_called_once_with(
        origin_url=f"https://github.com/USER/{repo_name}.git",
        target_dir=target_dir,
        upstream_url=f"https://github.com/{upstream_owner}/{repo_name}.git",
        new_branch=new_branch,
        base_branch=base_branch,
    )


def _github_api_json_fixture(name: str) -> dict:
    with Path(__file__).parent.joinpath(f"github_api/{name}.json").open() as f:
        return json.load(f)


@pytest.fixture()
def github_response_create_issue_comment() -> dict:
    return _github_api_json_fixture("create_issue_comment_pytest")


@pytest.fixture()
def github_response_create_pull_duplicate() -> dict:
    return _github_api_json_fixture("create_pull_duplicate")


@pytest.fixture()
def github_response_create_pull_validation_error() -> dict:
    return _github_api_json_fixture("create_pull_validation_error")


@pytest.fixture()
def github_response_get_pull() -> dict:
    return _github_api_json_fixture("get_pull_pytest")


@pytest.fixture()
def github_response_get_repo() -> dict:
    return _github_api_json_fixture("get_repo_pytest")


@pytest.fixture()
def create_pull_response_headers() -> dict:
    return _github_api_json_fixture("create_pull_response_headers")


def test_github_backend_from_token():
    token = "TOKEN"

    backend = GitHubBackend.from_token(token)

    assert backend.github3_client.session.auth.token == token
    # we cannot verify the pygithub token trivially


@pytest.mark.parametrize("does_exist", [True, False])
def test_github_backend_does_repository_exist(does_exist: bool):
    github3_client = MagicMock()

    backend = GitHubBackend(github3_client, MagicMock(), "")
    response = MagicMock()
    response.status_code = 200 if does_exist else 404

    if not does_exist:
        github3_client.repository.side_effect = github3.exceptions.NotFoundError(
            response
        )
    else:
        github3_client.repository.return_value = MagicMock()

    assert backend.does_repository_exist("OWNER", "REPO") is does_exist
    github3_client.repository.assert_called_once_with("OWNER", "REPO")


def test_github_backend_get_remote_url_https():
    owner = "OWNER"
    repo = "REPO"
    backend = GitHubBackend(MagicMock(), MagicMock(), "")

    url = backend.get_remote_url(owner, repo, GitConnectionMode.HTTPS)

    assert url == f"https://github.com/{owner}/{repo}.git"


@mock.patch("time.sleep", return_value=None)
@mock.patch(
    "conda_forge_tick.git_utils.GitHubBackend.user", new_callable=mock.PropertyMock
)
@mock.patch("conda_forge_tick.git_utils.GitHubBackend.does_repository_exist")
def test_github_backend_fork_not_exists_repo_found(
    exists_mock: MagicMock, user_mock: MagicMock, sleep_mock: MagicMock
):
    exists_mock.return_value = False

    github3_client = MagicMock()
    repository = MagicMock()
    github3_client.repository.return_value = repository

    backend = GitHubBackend(github3_client, MagicMock(), "")
    user_mock.return_value = "USER"
    backend.fork("UPSTREAM-OWNER", "REPO")

    exists_mock.assert_called_once_with("USER", "REPO")
    github3_client.repository.assert_called_once_with("UPSTREAM-OWNER", "REPO")
    repository.create_fork.assert_called_once()
    sleep_mock.assert_called_once_with(5)


@mock.patch("conda_forge_tick.git_utils.GitCli.clear_token")
@mock.patch("conda_forge_tick.git_utils.GitCli.add_token")
@mock.patch("conda_forge_tick.git_utils.GitCli.push_to_url")
def test_github_backend_push_to_repository(
    push_to_url_mock: MagicMock,
    add_token_mock: MagicMock,
    clear_token_mock: MagicMock,
    tmp_path: Path,
):
    backend = GitHubBackend.from_token("THIS_IS_THE_TOKEN")

    git_dir = tmp_path

    backend.push_to_repository("OWNER", "REPO", git_dir, "BRANCH_NAME")

    add_token_mock.assert_called_once_with(
        git_dir,
        "https://github.com",
        "THIS_IS_THE_TOKEN",
    )

    push_to_url_mock.assert_called_once_with(
        git_dir,
        "https://github.com/OWNER/REPO.git",
        "BRANCH_NAME",
    )

    clear_token_mock.assert_called_once_with(git_dir, "https://github.com")


@pytest.mark.parametrize("branch_already_synced", [True, False])
@mock.patch("time.sleep", return_value=None)
@mock.patch(
    "conda_forge_tick.git_utils.GitHubBackend.user", new_callable=mock.PropertyMock
)
@mock.patch("conda_forge_tick.git_utils.GitHubBackend.does_repository_exist")
def test_github_backend_fork_exists(
    exists_mock: MagicMock,
    user_mock: MagicMock,
    sleep_mock: MagicMock,
    branch_already_synced: bool,
    caplog,
):
    caplog.set_level(logging.DEBUG)

    exists_mock.return_value = True
    user_mock.return_value = "USER"

    pygithub_client = MagicMock()
    upstream_repo = MagicMock()
    fork_repo = MagicMock()

    def get_repo(full_name: str):
        if full_name == "UPSTREAM-OWNER/REPO":
            return upstream_repo
        if full_name == "USER/REPO":
            return fork_repo
        assert False, f"Unexpected repo full name: {full_name}"

    pygithub_client.get_repo.side_effect = get_repo

    if branch_already_synced:
        upstream_repo.default_branch = "BRANCH_NAME"
        fork_repo.default_branch = "BRANCH_NAME"
    else:
        upstream_repo.default_branch = "UPSTREAM_BRANCH_NAME"
        fork_repo.default_branch = "FORK_BRANCH_NAME"

    backend = GitHubBackend(MagicMock(), pygithub_client, "")
    backend.fork("UPSTREAM-OWNER", "REPO")

    if not branch_already_synced:
        pygithub_client.get_repo.assert_any_call("UPSTREAM-OWNER/REPO")
        pygithub_client.get_repo.assert_any_call("USER/REPO")

        assert "Syncing default branch" in caplog.text
        sleep_mock.assert_called_once_with(5)


@mock.patch(
    "conda_forge_tick.git_utils.GitHubBackend.user", new_callable=mock.PropertyMock
)
@mock.patch("conda_forge_tick.git_utils.GitHubBackend.does_repository_exist")
def test_github_backend_remote_does_not_exist(
    exists_mock: MagicMock, user_mock: MagicMock
):
    exists_mock.return_value = False

    github3_client = MagicMock()
    response = MagicMock()
    response.status_code = 404
    github3_client.repository.side_effect = github3.exceptions.NotFoundError(response)

    backend = GitHubBackend(github3_client, MagicMock(), "")

    user_mock.return_value = "USER"

    with pytest.raises(RepositoryNotFoundError):
        backend.fork("UPSTREAM-OWNER", "REPO")

    exists_mock.assert_called_once_with("USER", "REPO")
    github3_client.repository.assert_called_once_with("UPSTREAM-OWNER", "REPO")


def test_github_backend_user():
    pygithub_client = MagicMock()
    user = MagicMock()
    user.login = "USER"
    pygithub_client.get_user.return_value = user

    backend = GitHubBackend(MagicMock(), pygithub_client, "")

    for _ in range(4):
        # cached property
        assert backend.user == "USER"

    pygithub_client.get_user.assert_called_once()


def test_github_backend_get_api_requests_left_github_exception(caplog):
    github3_client = MagicMock()
    github3_client.rate_limit.side_effect = github3.exceptions.GitHubException(
        "API Error"
    )

    backend = GitHubBackend(github3_client, MagicMock(), "")

    assert backend.get_api_requests_left() is None
    assert "API error while fetching" in caplog.text

    github3_client.rate_limit.assert_called_once()


def test_github_backend_get_api_requests_left_unexpected_response_schema(caplog):
    github3_client = MagicMock()
    github3_client.rate_limit.return_value = {"some": "gibberish data"}

    backend = GitHubBackend(github3_client, MagicMock(), "")

    assert backend.get_api_requests_left() is None
    assert "API Error while parsing"

    github3_client.rate_limit.assert_called_once()


def test_github_backend_get_api_requests_left_nonzero():
    github3_client = MagicMock()
    github3_client.rate_limit.return_value = {"resources": {"core": {"remaining": 5}}}

    backend = GitHubBackend(github3_client, MagicMock(), "")

    assert backend.get_api_requests_left() == 5

    github3_client.rate_limit.assert_called_once()


def test_github_backend_get_api_requests_left_zero_invalid_reset_time(caplog):
    github3_client = MagicMock()

    github3_client.rate_limit.return_value = {"resources": {"core": {"remaining": 0}}}

    backend = GitHubBackend(github3_client, MagicMock(), "")

    assert backend.get_api_requests_left() == 0

    github3_client.rate_limit.assert_called_once()
    assert "GitHub API error while fetching rate limit reset time" in caplog.text


def test_github_backend_get_api_requests_left_zero_valid_reset_time(caplog):
    caplog.set_level(logging.INFO)

    github3_client = MagicMock()

    reset_timestamp = 1716303697
    reset_timestamp_str = "2024-05-21T15:01:37Z"

    github3_client.rate_limit.return_value = {
        "resources": {"core": {"remaining": 0, "reset": reset_timestamp}}
    }

    backend = GitHubBackend(github3_client, MagicMock(), "")

    assert backend.get_api_requests_left() == 0

    github3_client.rate_limit.assert_called_once()
    assert f"will reset at {reset_timestamp_str}" in caplog.text


@mock.patch("requests.Session.request")
def test_github_backend_create_pull_request_mock(
    request_mock: MagicMock,
    github_response_get_repo: dict,
    create_pull_response_headers: dict,
    github_response_get_pull: dict,
):
    def request_side_effect(method, _url, **_kwargs):
        response = requests.Response()
        if method == "GET":
            response.status_code = 200
            response.json = lambda: github_response_get_repo
            return response
        if method == "POST":
            response.status_code = 201
            # note that the "create pull" response body is identical to the "get pull" response body
            response.json = lambda: github_response_get_pull
            response.headers = CaseInsensitiveDict(create_pull_response_headers)
            return response
        assert False, f"Unexpected method: {method}"

    request_mock.side_effect = request_side_effect

    pygithub_mock = MagicMock()
    pygithub_mock.get_user.return_value.login = "CURRENT_USER"

    backend = GitHubBackend(github3.login(token="TOKEN"), pygithub_mock, "")

    pr_data = backend.create_pull_request(
        "conda-forge",
        "pytest-feedstock",
        "BASE_BRANCH",
        "HEAD_BRANCH",
        "TITLE",
        "BODY",
    )

    request_mock.assert_called_with(
        "POST",
        "https://api.github.com/repos/conda-forge/pytest-feedstock/pulls",
        data='{"title": "TITLE", "body": "BODY", "base": "BASE_BRANCH", "head": "CURRENT_USER:HEAD_BRANCH"}',
        json=None,
        timeout=mock.ANY,
    )

    assert pr_data.base is not None
    assert pr_data.base.repo.name == "pytest-feedstock"
    assert pr_data.closed_at is None
    assert pr_data.created_at is not None
    assert pr_data.created_at == datetime.datetime(
        2024, 5, 3, 17, 4, 20, tzinfo=datetime.timezone.utc
    )
    assert pr_data.head is not None
    assert pr_data.head.ref == "HEAD_BRANCH"
    assert (
        str(pr_data.html_url)
        == "https://github.com/conda-forge/pytest-feedstock/pull/1337"
    )
    assert pr_data.id == 1853804278
    assert pr_data.labels == []
    assert pr_data.mergeable is True
    assert pr_data.mergeable_state == GithubPullRequestMergeableState.CLEAN
    assert pr_data.merged is False
    assert pr_data.merged_at is None
    assert pr_data.number == 1337
    assert pr_data.state == PullRequestState.OPEN
    assert pr_data.updated_at == datetime.datetime(
        2024, 5, 27, 13, 31, 50, tzinfo=datetime.timezone.utc
    )

    assert (
        pr_data.e_tag
        == '"9995f8b0b0fe850244173c40390fbe8cb00fe525d7e58954bd6dd4bbcb74785a"'
    )
    assert pr_data.last_modified is None


@mock.patch("requests.Session.request")
def test_github_backend_create_pull_request_duplicate(
    request_mock: MagicMock,
    github_response_get_repo: dict,
    github_response_create_pull_duplicate: dict,
):
    def request_side_effect(method, _url, **_kwargs):
        response = requests.Response()
        if method == "GET":
            response.status_code = 200
            response.json = lambda: github_response_get_repo
            return response
        if method == "POST":
            response.status_code = 422
            # note that the "create pull" response body is identical to the "get pull" response body
            response.json = lambda: github_response_create_pull_duplicate
            return response
        assert False, f"Unexpected method: {method}"

    request_mock.side_effect = request_side_effect

    pygithub_mock = MagicMock()
    pygithub_mock.get_user.return_value.login = "CURRENT_USER"

    backend = GitHubBackend(github3.login(token="TOKEN"), pygithub_mock, "")

    with pytest.raises(
        DuplicatePullRequestError,
        match="Pull request from CURRENT_USER:HEAD_BRANCH to conda-forge:BASE_BRANCH already exists",
    ):
        backend.create_pull_request(
            "conda-forge",
            "pytest-feedstock",
            "BASE_BRANCH",
            "HEAD_BRANCH",
            "TITLE",
            "BODY",
        )


@mock.patch("requests.Session.request")
def test_github_backend_create_pull_request_validation_error(
    request_mock: MagicMock,
    github_response_get_repo: dict,
    github_response_create_pull_validation_error: dict,
):
    """Test that other GitHub API 422 validation errors are not caught as DuplicatePullRequestError."""

    def request_side_effect(method, _url, **_kwargs):
        response = requests.Response()
        if method == "GET":
            response.status_code = 200
            response.json = lambda: github_response_get_repo
            return response
        if method == "POST":
            response.status_code = 422
            # note that the "create pull" response body is identical to the "get pull" response body
            response.json = lambda: github_response_create_pull_validation_error
            return response
        assert False, f"Unexpected method: {method}"

    request_mock.side_effect = request_side_effect

    pygithub_mock = MagicMock()
    pygithub_mock.get_user.return_value.login = "CURRENT_USER"

    backend = GitHubBackend(github3.login(token="TOKEN"), pygithub_mock, "")

    with pytest.raises(github3.exceptions.UnprocessableEntity):
        backend.create_pull_request(
            "conda-forge",
            "pytest-feedstock",
            "BASE_BRANCH",
            "HEAD_BRANCH",
            "TITLE",
            "BODY",
        )


@mock.patch("requests.Session.request")
def test_github_backend_comment_on_pull_request_success(
    request_mock: MagicMock,
    github_response_get_repo: dict,
    github_response_get_pull: dict,
    github_response_create_issue_comment: dict,
):
    def request_side_effect(method, url, **_kwargs):
        response = requests.Response()
        if (
            method == "GET"
            and url == "https://api.github.com/repos/conda-forge/pytest-feedstock"
        ):
            response.status_code = 200
            response.json = lambda: github_response_get_repo
            return response
        if (
            method == "GET"
            and url
            == "https://api.github.com/repos/conda-forge/pytest-feedstock/pulls/1337"
        ):
            response.status_code = 200
            response.json = lambda: github_response_get_pull
            return response
        if (
            method == "POST"
            and url
            == "https://api.github.com/repos/conda-forge/pytest-feedstock/issues/1337/comments"
        ):
            response.status_code = 201
            response.json = lambda: github_response_create_issue_comment
            return response
        assert False, f"Unexpected endpoint: {method} {url}"

    request_mock.side_effect = request_side_effect

    backend = GitHubBackend(github3.login(token="TOKEN"), MagicMock(), "")

    backend.comment_on_pull_request(
        "conda-forge",
        "pytest-feedstock",
        1337,
        "COMMENT",
    )

    request_mock.assert_called_with(
        "POST",
        "https://api.github.com/repos/conda-forge/pytest-feedstock/issues/1337/comments",
        data='{"body": "COMMENT"}',
        json=None,
        timeout=mock.ANY,
    )


@mock.patch("requests.Session.request")
def test_github_backend_comment_on_pull_request_repo_not_found(request_mock: MagicMock):
    def request_side_effect(method, url, **_kwargs):
        response = requests.Response()
        if (
            method == "GET"
            and url == "https://api.github.com/repos/conda-forge/pytest-feedstock"
        ):
            response.status_code = 404
            return response
        assert False, f"Unexpected endpoint: {method} {url}"

    request_mock.side_effect = request_side_effect

    backend = GitHubBackend(github3.login(token="TOKEN"), MagicMock(), "")

    with pytest.raises(RepositoryNotFoundError):
        backend.comment_on_pull_request(
            "conda-forge",
            "pytest-feedstock",
            1337,
            "COMMENT",
        )


@mock.patch("requests.Session.request")
def test_github_backend_comment_on_pull_request_pull_request_not_found(
    request_mock: MagicMock,
    github_response_get_repo: dict,
):
    def request_side_effect(method, url, **_kwargs):
        response = requests.Response()
        if (
            method == "GET"
            and url == "https://api.github.com/repos/conda-forge/pytest-feedstock"
        ):
            response.status_code = 200
            response.json = lambda: github_response_get_repo
            return response
        if (
            method == "GET"
            and url
            == "https://api.github.com/repos/conda-forge/pytest-feedstock/pulls/1337"
        ):
            response.status_code = 404
            return response
        assert False, f"Unexpected endpoint: {method} {url}"

    request_mock.side_effect = request_side_effect
    backend = GitHubBackend(github3.login(token="TOKEN"), MagicMock(), "")

    with pytest.raises(
        GitPlatformError,
        match="Pull request conda-forge/pytest-feedstock#1337 not found",
    ):
        backend.comment_on_pull_request(
            "conda-forge",
            "pytest-feedstock",
            1337,
            "COMMENT",
        )


@mock.patch("requests.Session.request")
def test_github_backend_comment_on_pull_request_unexpected_response(
    request_mock: MagicMock,
    github_response_get_repo: dict,
    github_response_get_pull: dict,
):
    def request_side_effect(method, url, **_kwargs):
        response = requests.Response()
        if (
            method == "GET"
            and url == "https://api.github.com/repos/conda-forge/pytest-feedstock"
        ):
            response.status_code = 200
            response.json = lambda: github_response_get_repo
            return response
        if (
            method == "GET"
            and url
            == "https://api.github.com/repos/conda-forge/pytest-feedstock/pulls/1337"
        ):
            response.status_code = 200
            response.json = lambda: github_response_get_pull
            return response
        if (
            method == "POST"
            and url
            == "https://api.github.com/repos/conda-forge/pytest-feedstock/issues/1337/comments"
        ):
            response.status_code = 500
            return response
        assert False, f"Unexpected endpoint: {method} {url}"

    request_mock.side_effect = request_side_effect

    backend = GitHubBackend(github3.login(token="TOKEN"), MagicMock(), "")

    with pytest.raises(GitPlatformError, match="Could not comment on pull request"):
        backend.comment_on_pull_request(
            "conda-forge",
            "pytest-feedstock",
            1337,
            "COMMENT",
        )


def test_dry_run_backend_get_api_requests_left():
    backend = DryRunBackend()

    assert backend.get_api_requests_left() is Bound.INFINITY


def test_dry_run_backend_does_repository_exist_own_repo():
    backend = DryRunBackend()

    assert not backend.does_repository_exist(
        "auto-tick-bot-dry-run", "pytest-feedstock"
    )
    backend.fork("conda-forge", "pytest-feedstock")
    assert backend.does_repository_exist("auto-tick-bot-dry-run", "pytest-feedstock")


def test_dry_run_backend_does_repository_exist_other_repo():
    backend = DryRunBackend()

    assert backend.does_repository_exist("conda-forge", "pytest-feedstock")
    assert not backend.does_repository_exist(
        "conda-forge", "this-repository-does-not-exist"
    )


def test_dry_run_backend_get_remote_url_non_fork():
    backend = DryRunBackend()

    url = backend.get_remote_url("OWNER", "REPO", GitConnectionMode.HTTPS)

    assert url == "https://github.com/OWNER/REPO.git"


def test_dry_run_backend_get_remote_url_non_existing_fork():
    backend = DryRunBackend()

    with pytest.raises(RepositoryNotFoundError, match="does not exist"):
        backend.get_remote_url(backend.user, "REPO", GitConnectionMode.HTTPS)

    backend.fork("conda-forge", "pytest-feedstock")

    with pytest.raises(RepositoryNotFoundError, match="does not exist"):
        backend.get_remote_url(
            backend.user, "pydantic-feedstock", GitConnectionMode.HTTPS
        )


def test_dry_run_backend_get_remote_url_existing_fork():
    backend = DryRunBackend()

    backend.fork("conda-forge", "pytest-feedstock")

    url = backend.get_remote_url(
        backend.user,
        "pytest-feedstock",
        GitConnectionMode.HTTPS,
    )

    # note that the URL does not indicate anymore that it is a fork
    assert url == "https://github.com/conda-forge/pytest-feedstock.git"


def test_dry_run_backend_push_to_repository(caplog, tmp_path: Path):
    caplog.set_level(logging.DEBUG)

    backend = DryRunBackend()

    git_dir = tmp_path

    backend.push_to_repository("OWNER", "REPO", git_dir, "BRANCH_NAME")

    assert (
        f"Dry Run: Pushing changes from {git_dir} to OWNER/REPO on branch BRANCH_NAME"
        in caplog.text
    )


def test_dry_run_backend_fork(caplog):
    caplog.set_level(logging.DEBUG)

    backend = DryRunBackend()

    backend.fork("conda-forge", "pytest-feedstock")
    assert (
        "Dry Run: Creating fork of conda-forge/pytest-feedstock for user auto-tick-bot-dry-run"
        in caplog.text
    )

    with pytest.raises(RepositoryNotFoundError):
        backend.fork("conda-forge", "this-repository-does-not-exist")


def test_dry_run_backend_sync_default_branch(caplog):
    caplog.set_level(logging.DEBUG)

    backend = DryRunBackend()

    backend._sync_default_branch("UPSTREAM_OWNER", "REPO")

    assert "Dry Run: Syncing default branch of UPSTREAM_OWNER/REPO" in caplog.text


def test_dry_run_backend_user():
    backend = DryRunBackend()

    assert backend.user == "auto-tick-bot-dry-run"


def test_dry_run_backend_create_pull_request(caplog):
    backend = DryRunBackend()
    caplog.set_level(logging.DEBUG)

    body_text = "This is a long\nbody text"

    pr_data = backend.create_pull_request(
        "conda-forge",
        "pytest-feedstock",
        "BASE_BRANCH",
        "HEAD_BRANCH",
        "TITLE",
        body_text,
    )

    # caplog validation
    assert "Create Pull Request" in caplog.text
    assert 'Title: "TITLE"' in caplog.text
    assert "Target Repository: conda-forge/pytest-feedstock" in caplog.text
    assert (
        f"Branches: {backend.user}:HEAD_BRANCH -> conda-forge:BASE_BRANCH"
        in caplog.text
    )
    assert f"Body:\n{body_text}" in caplog.text

    # pr_data validation
    assert pr_data.e_tag == "GITHUB_PR_ETAG"
    assert pr_data.last_modified is not None
    assert pr_data.id == 13371337
    assert (
        str(pr_data.html_url)
        == "https://github.com/conda-forge/pytest-feedstock/pulls/1337"
    )
    assert pr_data.created_at is not None
    assert pr_data.number == 1337
    assert pr_data.state == PullRequestState.OPEN
    assert pr_data.head.ref == "HEAD_BRANCH"
    assert pr_data.base.repo.name == "pytest-feedstock"


def test_dry_run_backend_comment_on_pull_request(caplog):
    backend = DryRunBackend()
    caplog.set_level(logging.DEBUG)

    comment_text = "This is a long\ncomment text"

    backend.comment_on_pull_request(
        "conda-forge",
        "pytest-feedstock",
        1337,
        comment_text,
    )

    assert "Comment on Pull Request" in caplog.text
    assert f"Comment:\n{comment_text}" in caplog.text
    assert "Pull Request: conda-forge/pytest-feedstock#1337" in caplog.text


def test_trim_pr_json_keys():
    pr_json = {
        "ETag": "blah",
        "Last-Modified": "flah",
        "last_fetched": "2024-01-01T00:00:00+00:00",
        "id": 435,
        "random": "string",
        "head": {"reff": "foo"},
        "base": {"repo": {"namee": "None", "name": "foo"}},
    }

    pr_json = trim_pr_json_keys(pr_json)
    assert "random" not in pr_json
    assert pr_json["head"] == {}
    assert pr_json["base"]["repo"] == {"name": "foo"}
    assert pr_json["id"] == 435
    assert pr_json["last_fetched"] == "2024-01-01T00:00:00+00:00"


def test_trim_pr_json_keys_src():
    src_pr_json = {
        "ETag": "blah",
        "Last-Modified": "flah",
        "last_fetched": "2024-01-01T00:00:00+00:00",
        "id": 435,
        "random": "string",
        "head": {"reff": "foo"},
        "base": {"repo": {"namee": "None", "name": "foo"}},
    }

    pr_json = trim_pr_json_keys({"r": None}, src_pr_json=src_pr_json)
    assert "random" not in pr_json
    assert pr_json["head"] == {}
    assert pr_json["base"]["repo"] == {"name": "foo"}
    assert pr_json["id"] == 435
    assert "r" not in pr_json
    assert pr_json["last_fetched"] == "2024-01-01T00:00:00+00:00"


@pytest.mark.skipif(
    not conda_forge_tick.global_sensitive_env.classified_info.get("BOT_TOKEN", None),
    reason="No token for live tests.",
)
def test_git_utils_push_and_delete_file_via_gh_api():
    uid = uuid.uuid4().hex
    node = f"test_file_h{uid}"
    fname = node + ".json"

    repo_name = "regro/cf-graph-countyfair"
    gh = github_client()
    repo = gh.get_repo(repo_name)

    # to make the i/o nice for -s
    print("", flush=True)

    def _sleep():
        print("sleeping for 5 seconds to allow github to update", flush=True)
        time.sleep(5)

    with tempfile.TemporaryDirectory() as tmpdir, pushd(str(tmpdir)):
        try:
            with open(fname, "w") as f:
                f.write('{"uid": "initial_uid"}')
            push_file_via_gh_api(fname, repo_name, f"testing - push - {fname}")
            _sleep()
            _, data = _get_pth_blob_sha_and_content(fname, repo)
            assert json.loads(data)["uid"] == "initial_uid"

            with open(fname, "w") as f:
                f.write('{"uid": "new_uid"}')
            push_file_via_gh_api(fname, repo_name, f"testing - push - {fname}")
            _sleep()
            sha, data = _get_pth_blob_sha_and_content(fname, repo)
            assert json.loads(data)["uid"] == "new_uid"

            push_file_via_gh_api(fname, repo_name, f"testing - push - {fname}")
            _sleep()
            new_sha, data = _get_pth_blob_sha_and_content(fname, repo)
            assert sha == new_sha

            delete_file_via_gh_api(fname, repo_name, f"testing - delete - {fname}")
            _sleep()
            new_sha, data = _get_pth_blob_sha_and_content(fname, repo)
            assert new_sha is None
            assert data is None
        finally:
            message = f"remove files {fname} from testing"
            for tr in range(10):
                try:
                    contents = repo.get_contents(fname)
                    repo.delete_file(fname, message, contents.sha)
                    break
                except Exception:
                    pass
