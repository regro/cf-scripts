import subprocess
import tempfile
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

import pytest

from conda_forge_tick.git_utils import (
    GitCli,
    GitCliError,
    GitConnectionMode,
    GitHubBackend,
    GitPlatformBackend,
    RepositoryNotFoundError,
    trim_pr_json_keys,
)

"""
Note: You have to have git installed on your machine to run these tests.
"""


@mock.patch("subprocess.run")
@pytest.mark.parametrize("check_error", [True, False])
def test_git_cli_run_git_command_no_error(
    subprocess_run_mock: MagicMock, check_error: bool
):
    cli = GitCli()

    working_directory = Path("TEST_DIR")

    cli._run_git_command(
        ["GIT_COMMAND", "ARG1", "ARG2"], working_directory, check_error
    )

    subprocess_run_mock.assert_called_once_with(
        ["git", "GIT_COMMAND", "ARG1", "ARG2"], check=check_error, cwd=working_directory
    )


@mock.patch("subprocess.run")
def test_git_cli_run_git_command_error(subprocess_run_mock: MagicMock):
    cli = GitCli()

    working_directory = Path("TEST_DIR")

    subprocess_run_mock.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd=""
    )

    with pytest.raises(GitCliError):
        cli._run_git_command(["GIT_COMMAND"], working_directory)


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


def test_git_cli_reset_hard_already_reset():
    cli = GitCli()
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        cli._run_git_command(["init"], working_directory=dir_path)
        cli._run_git_command(
            ["commit", "--allow-empty", "-m", "Initial commit"],
            working_directory=dir_path,
        )

        cli.reset_hard(dir_path)


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_reset_hard_mock(run_git_command_mock: MagicMock):
    cli = GitCli()

    git_dir = Path("TEST_DIR")

    cli.reset_hard(git_dir)

    run_git_command_mock.assert_called_once_with(
        ["reset", "--quiet", "--hard", "HEAD"], git_dir
    )


def test_git_cli_reset_hard():
    cli = GitCli()
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        cli._run_git_command(["init"], working_directory=dir_path)
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

        # delete the README.md file
        readme_file.unlink()

        assert not readme_file.exists()

        # clone the repo again (in the same directory!) - this should reset the repo
        cli.clone_repo(git_url, dir_path)

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

        # now we simulate that the repo already exists
        dir_path.mkdir()

        cli.clone_repo(git_url, dir_path)

        reset_hard_mock.assert_called_once_with(dir_path)


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
def test_git_cli_add_remote_mock(run_git_command_mock: MagicMock):
    cli = GitCli()

    git_dir = Path("TEST_DIR")
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

        cli._run_git_command(["init"], working_directory=dir_path)

        remote_name = "remote24"
        remote_url = "https://git-repository.com/repo.git"

        cli.add_remote(dir_path, remote_name, remote_url)

        output = subprocess.run(
            "git remote -v", cwd=dir_path, shell=True, capture_output=True
        )

        assert remote_name in output.stdout.decode()
        assert remote_url in output.stdout.decode()


@mock.patch("conda_forge_tick.git_utils.GitCli._run_git_command")
def test_git_cli_fetch_all_mock(run_git_command_mock: MagicMock):
    cli = GitCli()

    git_dir = Path("TEST_DIR")

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

        cli._run_git_command(["init"], working_directory=dir_path)

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
    run_git_command_mock: MagicMock, does_exist: bool
):
    cli = GitCli()

    git_dir = Path("TEST_DIR")
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
def test_git_cli_checkout_branch_mock(run_git_command_mock: MagicMock, track: bool):
    branch_name = "BRANCH_NAME"

    cli = GitCli()
    git_dir = Path("TEST_DIR")

    cli.checkout_branch(git_dir, branch_name, track=track)

    track_flag = ["--track"] if track else []

    run_git_command_mock.assert_called_once_with(
        ["checkout", "--quiet", *track_flag, branch_name], git_dir
    )


def test_git_cli_checkout_branch_no_track():
    cli = GitCli()

    with tempfile.TemporaryDirectory() as tmpdir:
        dir_path = Path(tmpdir)

        cli._run_git_command(["init"], working_directory=dir_path)
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
    caplog,
):
    fork_url = "https://github.com/regro-cf-autotick-bot/pytest-feedstock.git"
    upstream_url = "https://github.com/conda-forge/pytest-feedstock.git"
    git_dir = Path("TEST_DIR")

    caplog.set_level("DEBUG")

    cli = GitCli()

    if remote_already_exists:
        add_remote_mock.side_effect = GitCliError("Remote already exists")

    does_branch_exist_mock.return_value = base_branch_exists

    def checkout_branch_side_effect(_git_dir: Path, branch: str, track: bool = False):
        if track and git_checkout_track_error:
            raise GitCliError("Error checking out branch with --track")

        if new_branch_already_exists and branch == "new_branch_name":
            raise GitCliError("Branch new_branch_name already exists")

    checkout_branch_mock.side_effect = checkout_branch_side_effect

    cli.clone_fork_and_branch(
        fork_url, git_dir, upstream_url, "new_branch_name", "base_branch"
    )

    clone_repo_mock.assert_called_once_with(fork_url, git_dir)
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

    reset_hard_mock.assert_called_once_with(git_dir, "upstream/base_branch")
    checkout_branch_mock.assert_any_call(git_dir, "new_branch_name")

    if not new_branch_already_exists:
        return

    assert "branch new_branch_name does not exist" in caplog.text
    checkout_new_branch_mock.assert_called_with(
        git_dir, "new_branch_name", start_point="base_branch"
    )


def test_git_platform_backend_get_remote_url_https():
    owner = "OWNER"
    repo = "REPO"

    url = GitPlatformBackend.get_remote_url(owner, repo, GitConnectionMode.HTTPS)

    assert url == f"https://github.com/{owner}/{repo}.git"


def test_git_platform_backend_get_remote_url_ssh():
    owner = "OWNER"
    repo = "REPO"

    url = GitPlatformBackend.get_remote_url(owner, repo, GitConnectionMode.SSH)

    assert url == f"git@github.com:{owner}/{repo}.git"


def test_github_backend_from_token():
    token = "TOKEN"

    backend = GitHubBackend.from_token(token)

    assert backend.github3_client.session.auth.token == token
    # we cannot verify the pygithub token trivially


@pytest.mark.parametrize("does_exist", [True, False])
def test_github_backend_does_repository_exist(does_exist: bool):
    github3_client = MagicMock()

    backend = GitHubBackend(github3_client, MagicMock())

    github3_client.repository.return_value = MagicMock() if does_exist else None

    assert backend.does_repository_exist("OWNER", "REPO") is does_exist
    github3_client.repository.assert_called_once_with("OWNER", "REPO")


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

    backend = GitHubBackend(github3_client, MagicMock())
    user_mock.return_value = "USER"
    backend.fork("UPSTREAM-OWNER", "REPO")

    exists_mock.assert_called_once_with("USER", "REPO")
    github3_client.repository.assert_called_once_with("UPSTREAM-OWNER", "REPO")
    repository.create_fork.assert_called_once()
    sleep_mock.assert_called_once_with(5)


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
    caplog.set_level("DEBUG")

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

    backend = GitHubBackend(MagicMock(), pygithub_client)
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
    github3_client.repository.return_value = None

    backend = GitHubBackend(github3_client, MagicMock())

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

    backend = GitHubBackend(MagicMock(), pygithub_client)

    for _ in range(4):
        # cached property
        assert backend.user == "USER"

    pygithub_client.get_user.assert_called_once()


def test_trim_pr_json_keys():
    pr_json = {
        "ETag": "blah",
        "Last-Modified": "flah",
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


def test_trim_pr_json_keys_src():
    src_pr_json = {
        "ETag": "blah",
        "Last-Modified": "flah",
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
