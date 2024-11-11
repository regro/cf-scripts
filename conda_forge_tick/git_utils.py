"""Utilities for managing github repos"""

import base64
import copy
import enum
import logging
import math
import subprocess
import textwrap
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from email import utils
from functools import cached_property
from pathlib import Path
from typing import Dict, Iterator, Optional, Union

import backoff
import github
import github3
import github3.exceptions
import github3.pulls
import github3.repos
import requests
from github3.session import GitHubSession
from requests.exceptions import RequestException, Timeout
from requests.structures import CaseInsensitiveDict

from conda_forge_tick import sensitive_env
from conda_forge_tick.lazy_json_backends import LazyJson

from .executors import lock_git_operation
from .models.pr_json import (
    GithubPullRequestBase,
    GithubPullRequestMergeableState,
    GithubRepository,
    PullRequestDataValid,
    PullRequestInfoHead,
    PullRequestState,
)
from .utils import get_bot_run_url, run_command_hiding_token

logger = logging.getLogger(__name__)

backoff._decorator._is_event_loop = lambda: False

GITHUB3_CLIENT = threading.local()
GITHUB_CLIENT = threading.local()

MAX_GITHUB_TIMEOUT = 60

BOT_RERUN_LABEL = {
    "name": "bot-rerun",
}

CF_BOT_NAMES = {"regro-cf-autotick-bot", "conda-forge-linter"}

# these keys are kept from github PR json blobs
# to add more keys to keep, put them in the right spot in the dict and
# set them to None. Also add them to the PullRequestDataValid Pydantic model!
PR_KEYS_TO_KEEP = {
    "ETag": None,
    "Last-Modified": None,
    "id": None,
    "number": None,
    "html_url": None,
    "created_at": None,
    "updated_at": None,
    "merged_at": None,
    "closed_at": None,
    "state": None,
    "mergeable_state": None,
    "labels": None,
    "merged": None,
    "draft": None,
    "mergeable": None,
    "head": {"ref": None},
    "base": {"repo": {"name": None}},
}


def get_bot_token():
    with sensitive_env() as env:
        return env["BOT_TOKEN"]


def github3_client() -> github3.GitHub:
    """
    This will be removed in the future, use the GitHubBackend class instead.
    """
    if not hasattr(GITHUB3_CLIENT, "client"):
        GITHUB3_CLIENT.client = github3.login(token=get_bot_token())
    return GITHUB3_CLIENT.client


def github_client() -> github.Github:
    """
    This will be removed in the future, use the GitHubBackend class instead.
    """
    if not hasattr(GITHUB_CLIENT, "client"):
        GITHUB_CLIENT.client = github.Github(
            auth=github.Auth.Token(get_bot_token()),
            per_page=100,
        )
    return GITHUB_CLIENT.client


class Bound(float, enum.Enum):
    def __str__(self):
        return str(self.value)

    INFINITY = math.inf
    """
    Python does not have support for a literal infinity type, so we use this enum for it.
    """


class GitConnectionMode(enum.StrEnum):
    """
    We don't need anything else than HTTPS for now, but this would be the place to
    add more connection modes (e.g. SSH).
    """

    HTTPS = "https"


class GitCliError(Exception):
    """
    A generic error that occurred while running a git CLI command.
    """

    pass


class GitPlatformError(Exception):
    """
    A generic error that occurred while interacting with a git platform.
    """

    pass


class DuplicatePullRequestError(GitPlatformError):
    """
    Raised if a pull request already exists.
    """

    pass


class RepositoryNotFoundError(Exception):
    """
    Raised when a repository is not found.
    """

    pass


class GitCli:
    """
    A simple wrapper around the git command line interface.

    Git operations are locked (globally) to prevent operations from interfering with each other.
    If this does impact performance too much, we can consider a per-repository locking strategy.
    """

    @lock_git_operation()
    def _run_git_command(
        self,
        cmd: list[str | Path],
        working_directory: Path | None = None,
        check_error: bool = True,
        suppress_all_output: bool = False,
    ) -> subprocess.CompletedProcess:
        """
        Run a git command. stdout is by default only printed if the command fails. stderr is always printed by default.
        stdout is, by default, always available in the returned CompletedProcess, stderr is never.

        :param cmd: The command to run, as a list of strings.
        :param working_directory: The directory to run the command in. If None, the command will be run in the current
        working directory.
        :param check_error: If True, raise a GitCliError if the git command fails.
        :param suppress_all_output: If True, suppress all output (stdout and stderr). Also, the returned
        CompletedProcess will have stdout and stderr set to None. Use this for sensitive commands.
        :return: The result of the git command.
        :raises GitCliError: If the git command fails and check_error is True.
        :raises FileNotFoundError: If the working directory does not exist.
        """
        git_command = ["git"] + cmd

        logger.debug(f"Running git command: {git_command}")

        # stdout and stderr are piped to devnull if suppress_all_output is True
        stdout_args = (
            {"stdout": subprocess.PIPE}
            if not suppress_all_output
            else {"stdout": subprocess.DEVNULL}
        )
        stderr_args = {} if not suppress_all_output else {"stderr": subprocess.DEVNULL}

        try:
            p = subprocess.run(
                git_command,
                check=check_error,
                cwd=working_directory,
                **stdout_args,
                **stderr_args,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            logger.info(
                f"Command '{' '.join(map(str, git_command))}' failed.\nstdout:\n{e.stdout or '<None>'}\nend of stdout"
            )
            raise GitCliError(f"Error running git command: {repr(e)}")

        return p

    @lock_git_operation()
    def add(self, git_dir: Path, *pathspec: Path, all_: bool = False):
        """
        Add files to the git index with `git add`.
        :param git_dir: The directory of the git repository.
        :param pathspec: The files to add.
        :param all_: If True, not only add the files in pathspec, but also where the index already has an entry.
        If all_ is set with empty pathspec, all files in the entire working tree are updated.
        :raises ValueError: If pathspec is empty and all_ is False.
        :raises GitCliError: If the git command fails.
        """
        if not pathspec and not all_:
            raise ValueError("Either pathspec or all_ must be set.")

        all_arg = ["--all"] if all_ else []

        self._run_git_command(["add", *all_arg, *pathspec], git_dir)

    @lock_git_operation()
    def commit(
        self, git_dir: Path, message: str, all_: bool = False, allow_empty: bool = False
    ):
        """
        Commit changes to the git repository with `git commit`.
        :param git_dir: The directory of the git repository.
        :param message: The commit message.
        :param allow_empty: If True, allow an empty commit.
        :param all_: Automatically stage files that have been modified and deleted, but new files are not affected.
        :raises GitCliError: If the git command fails.
        """
        all_arg = ["-a"] if all_ else []
        allow_empty_arg = ["--allow-empty"] if allow_empty else []

        self._run_git_command(
            ["commit", *all_arg, *allow_empty_arg, "-m", message], git_dir
        )

    @lock_git_operation()
    def reset_hard(self, git_dir: Path, to_treeish: str = "HEAD"):
        """
        Reset the git index of a directory to the state of the last commit with `git reset --hard HEAD`.
        :param git_dir: The directory to reset.
        :param to_treeish: The treeish to reset to. Defaults to "HEAD".
        :raises GitCliError: If the git command fails.
        :raises FileNotFoundError: If the git_dir does not exist.
        """
        self._run_git_command(["reset", "--quiet", "--hard", to_treeish], git_dir)

    @lock_git_operation()
    def clone_repo(self, origin_url: str, target_dir: Path):
        """
        Clone a Git repository.
        If target_dir exists and is non-empty, this method will fail with GitCliError.
        If target_dir exists and is empty, it will work.
        If target_dir does not exist, it will work.
        :param target_dir: The directory to clone the repository into.
        :param origin_url: The URL of the repository to clone.
        :raises GitCliError: If the git command fails (e.g. because origin_url does not point to valid remote or
        target_dir is not empty).
        """
        try:
            self._run_git_command(["clone", "--quiet", origin_url, target_dir])
        except GitCliError as e:
            raise GitCliError(
                f"Error cloning repository from {origin_url}. Does the repository exist? Is target_dir empty?"
            ) from e

    @lock_git_operation()
    def push_to_url(self, git_dir: Path, remote_url: str, branch: str):
        """
        Push changes to a remote URL.
        :param git_dir: The directory of the git repository.
        :param remote_url: The URL of the remote.
        :param branch: The branch to push to.
        :raises GitCliError: If the git command fails.
        """

        self._run_git_command(["push", remote_url, branch], git_dir)

    @lock_git_operation()
    def add_remote(self, git_dir: Path, remote_name: str, remote_url: str):
        """
        Add a remote to a git repository.
        :param remote_name: The name of the remote.
        :param remote_url: The URL of the remote.
        :param git_dir: The directory of the git repository.
        :raises GitCliError: If the git command fails (e.g., the remote already exists).
        :raises FileNotFoundError: If git_dir does not exist
        """
        self._run_git_command(["remote", "add", remote_name, remote_url], git_dir)

    @lock_git_operation()
    def add_token(self, git_dir: Path, origin: str, token: str):
        """
        Configures git with a local configuration to use the given token for the given origin.
        Internally, this sets the `http.<origin>/.extraheader` git configuration key to
        `AUTHORIZATION: basic <base64-encoded HTTP basic token>`.
        This is similar to how the GitHub Checkout action does it:
        https://github.com/actions/checkout/blob/eef61447b9ff4aafe5dcd4e0bbf5d482be7e7871/adrs/0153-checkout-v2.md#PAT

        The CLI outputs of this command are suppressed to avoid leaking the token.
        :param git_dir: The directory of the git repository.
        :param origin: The origin to use the token for. Origin is SCHEME://HOST[:PORT] (without trailing slash).
        :param token: The token to use.
        """
        http_basic_token = base64.b64encode(f"x-access-token:{token}".encode()).decode()

        self._run_git_command(
            [
                "config",
                "--local",
                f"http.{origin}/.extraheader",
                f"AUTHORIZATION: basic {http_basic_token}",
            ],
            git_dir,
            suppress_all_output=True,
        )

    @lock_git_operation()
    def clear_token(self, git_dir, origin):
        """
        Clear the token for the given origin.
        :param git_dir: The directory of the git repository.
        :param origin: The origin to clear the token for.
        """
        self._run_git_command(
            [
                "config",
                "--local",
                "--unset",
                f"http.{origin}/.extraheader",
            ],
            git_dir,
        )

    @lock_git_operation()
    def fetch_all(self, git_dir: Path):
        """
        Fetch all changes from all remotes.
        :param git_dir: The directory of the git repository.
        :raises GitCliError: If the git command fails.
        :raises FileNotFoundError: If git_dir does not exist
        """
        self._run_git_command(["fetch", "--all", "--quiet"], git_dir)

    def does_branch_exist(self, git_dir: Path, branch_name: str):
        """
        Check if a branch exists in a git repository.
        Note: If git_dir is not a git repository, this method will return False.
        Note: This method is intentionally not locked with lock_git_operation, as it only reads the git repository and
        does not modify it.
        :param branch_name: The name of the branch.
        :param git_dir: The directory of the git repository.
        :return: True if the branch exists, False otherwise.
        :raises GitCliError: If the git command fails.
        :raises FileNotFoundError: If git_dir does not exist
        """
        ret = self._run_git_command(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            git_dir,
            check_error=False,
        )

        return ret.returncode == 0

    def does_remote_exist(self, remote_url: str) -> bool:
        """
        Check if a remote exists.
        Note: This method is intentionally not locked with lock_git_operation, as it only reads a remote and does not
        modify a git repository.
        :param remote_url: The URL of the remote.
        :return: True if the remote exists, False otherwise.
        """
        ret = self._run_git_command(["ls-remote", remote_url], check_error=False)

        return ret.returncode == 0

    @lock_git_operation()
    def checkout_branch(
        self,
        git_dir: Path,
        branch: str,
        track: bool = False,
    ):
        """
        Checkout a branch in a git repository.
        :param git_dir: The directory of the git repository.
        :param branch: The branch to check out.
        :param track: If True, set the branch to track the remote branch with the same name (sets the --track flag).
        A new local branch will be created with the name inferred from branch.
        For example, if branch is "upstream/main", the new branch will be "main".
        :raises GitCliError: If the git command fails.
        :raises FileNotFoundError: If git_dir does not exist
        """
        track_flag = ["--track"] if track else []
        self._run_git_command(
            ["checkout", "--quiet"] + track_flag + [branch],
            git_dir,
        )

    @lock_git_operation()
    def checkout_new_branch(
        self, git_dir: Path, branch: str, start_point: str | None = None
    ):
        """
        Checkout a new branch in a git repository.
        :param git_dir: The directory of the git repository.
        :param branch: The name of the new branch.
        :param start_point: The name of the branch to branch from, or None to branch from the current branch.
        :raises FileNotFoundError: If git_dir does not exist
        """
        start_point_option = [start_point] if start_point else []

        self._run_git_command(
            ["checkout", "--quiet", "-b", branch] + start_point_option, git_dir
        )

    def diffed_files(
        self, git_dir: Path, commit_a: str, commit_b: str = "HEAD"
    ) -> Iterator[Path]:
        """
        Get the files that are different between two commits.
        :param git_dir: The directory of the git repository. This should be the root of the repository.
            If it is a subdirectory, only the files in that subdirectory will be returned.
        :param commit_a: The first commit.
        :param commit_b: The second commit.
        :return: An iterator over the files that are different between the two commits.
        """

        # --relative ensures that we do not assemble invalid paths below if git_dir is a subdirectory
        ret = self._run_git_command(
            ["diff", "--name-only", "--relative", commit_a, commit_b],
            git_dir,
        )

        return (git_dir / line for line in ret.stdout.splitlines())

    @lock_git_operation()
    def clone_fork_and_branch(
        self,
        origin_url: str,
        target_dir: Path,
        upstream_url: str,
        new_branch: str,
        base_branch: str = "main",
    ):
        """
        Convenience method to do the following:
        1. Clone the repository at origin_url into target_dir (resetting the directory if it already exists).
        2. Add a remote named "upstream" with the URL upstream_url (ignoring if it already exists).
        3. Fetch all changes from all remotes.
        4. Checkout the base branch.
        5. Create a new branch from the base branch with the name new_branch.

        This is usually used to create a new branch for a pull request. In this case, origin_url is the URL of the
        user's fork, and upstream_url is the URL of the upstream repository.

        :param origin_url: The URL of the repository (fork) to clone.
        :param target_dir: The directory to clone the repository into.
        :param upstream_url: The URL of the upstream repository.
        :param new_branch: The name of the branch to create.
        :param base_branch: The name of the base branch to branch from.

        :raises GitCliError: If a git command fails.
        """
        try:
            self.clone_repo(origin_url, target_dir)
        except GitCliError:
            if not target_dir.exists():
                raise GitCliError(
                    f"Could not clone {origin_url} - does the remote exist?"
                )
            logger.debug(
                f"Cloning {origin_url} into {target_dir} was not successful - "
                f"trying to reset hard since the directory already exists. This will fail if the target directory is "
                f"not a git repository."
            )
            self.reset_hard(target_dir)

        try:
            self.add_remote(target_dir, "upstream", upstream_url)
        except GitCliError as e:
            logger.debug(
                "It looks like remote 'upstream' already exists. Ignoring.", exc_info=e
            )
            pass

        self.fetch_all(target_dir)

        if self.does_branch_exist(target_dir, base_branch):
            self.checkout_branch(target_dir, base_branch)
        else:
            try:
                self.checkout_branch(target_dir, f"upstream/{base_branch}", track=True)
            except GitCliError as e:
                logger.debug(
                    "Could not check out with git checkout --track. Trying git checkout -b.",
                    exc_info=e,
                )

                # not sure why this is needed, but it was in the original code
                self.checkout_new_branch(
                    target_dir,
                    base_branch,
                    start_point=f"upstream/{base_branch}",
                )

        # not sure why this is needed, but it was in the original code
        self.reset_hard(target_dir, f"upstream/{base_branch}")

        try:
            logger.debug(
                f"Trying to checkout branch {new_branch} without creating a new branch"
            )
            self.checkout_branch(target_dir, new_branch)
        except GitCliError:
            logger.debug(
                f"It seems branch {new_branch} does not exist. Creating it.",
            )
            self.checkout_new_branch(target_dir, new_branch, start_point=base_branch)


class GitPlatformBackend(ABC):
    """
    A backend for interacting with a git platform (e.g. GitHub).

    Implementation Note: If you wonder what should be in this class vs. the GitCli class, the GitPlatformBackend class
    should contain the logic for interacting with the platform (e.g. GitHub), while the GitCli class should contain the
    logic for interacting with the git repository itself. If you need to know anything specific about the platform,
    it should be in the GitPlatformBackend class.

    Git operations are locked (globally) to prevent operations from interfering with each other.
    If this does impact performance too much, we can consider a per-repository locking strategy.
    """

    # Currently we don't need any abstraction for other platforms than GitHub, so we don't build such abstractions.
    GIT_PLATFORM_ORIGIN = "https://github.com"

    def __init__(self, git_cli: GitCli):
        """
        Create a new GitPlatformBackend.
        :param git_cli: The GitCli instance to use for interacting with git repositories.
        """
        self.cli = git_cli

    @abstractmethod
    def does_repository_exist(self, owner: str, repo_name: str) -> bool:
        """
        Check if a repository exists.
        :param owner: The owner of the repository.
        :param repo_name: The name of the repository.
        """
        pass

    def get_remote_url(
        self,
        owner: str,
        repo_name: str,
        connection_mode: GitConnectionMode = GitConnectionMode.HTTPS,
    ) -> str:
        """
        Get the URL of a remote repository.
        :param owner: The owner of the repository.
        :param repo_name: The name of the repository.
        :param connection_mode: The connection mode to use.
        :raises ValueError: If the connection mode is not supported.
        :raises RepositoryNotFoundError: If the repository does not exist. This is only raised if the backend relies on
        the repository existing to generate the URL.
        """
        match connection_mode:
            case GitConnectionMode.HTTPS:
                return f"{self.GIT_PLATFORM_ORIGIN}/{owner}/{repo_name}.git"
            case _:
                raise ValueError(f"Unsupported connection mode: {connection_mode}")

    @abstractmethod
    def push_to_repository(
        self, owner: str, repo_name: str, git_dir: Path, branch: str
    ):
        """
        Push changes to a repository.
        :param owner: The owner of the repository.
        :param repo_name: The name of the repository.
        :param git_dir: The directory of the git repository.
        :param branch: The branch to push to.
        :raises GitPlatformError: If the push fails.
        """
        pass

    @abstractmethod
    def fork(self, owner: str, repo_name: str):
        """
        Fork a repository. If the fork already exists, do nothing except syncing the default branch name.
        Forks are created under the current user's account (see `self.user`).
        The name of the forked repository is the same as the original repository.
        :param owner: The owner of the repository.
        :param repo_name: The name of the repository.
        :raises RepositoryNotFoundError: If the repository does not exist.
        """
        pass

    @lock_git_operation()
    def clone_fork_and_branch(
        self,
        upstream_owner: str,
        repo_name: str,
        target_dir: Path,
        new_branch: str,
        base_branch: str = "main",
    ):
        """
        Identical to `GitCli::clone_fork_and_branch`, but generates the URLs from the repository name.

        :param upstream_owner: The owner of the upstream repository.
        :param repo_name: The name of the repository.
        :param target_dir: The directory to clone the repository into.
        :param new_branch: The name of the branch to create.
        :param base_branch: The name of the base branch to branch from.

        :raises GitCliError: If a git command fails.
        """
        self.cli.clone_fork_and_branch(
            origin_url=self.get_remote_url(self.user, repo_name),
            target_dir=target_dir,
            upstream_url=self.get_remote_url(upstream_owner, repo_name),
            new_branch=new_branch,
            base_branch=base_branch,
        )

    @property
    @abstractmethod
    def user(self) -> str:
        """
        The username of the logged-in user, i.e. the owner of forked repositories.
        """
        pass

    @abstractmethod
    def _sync_default_branch(self, upstream_owner: str, upstream_repo: str):
        """
        Sync the default branch of the forked repository with the upstream repository.
        :param upstream_owner: The owner of the upstream repository.
        :param upstream_repo: The name of the upstream repository.
        """
        pass

    @abstractmethod
    def get_api_requests_left(self) -> int | Bound | None:
        """
        Get the number of remaining API requests for the backend.
        Returns `Bound.INFINITY` if the backend does not have a rate limit.
        Returns None if an exception occurred while getting the rate limit.

        Implementations may print diagnostic information about the API limit.
        """
        pass

    def is_api_limit_reached(self) -> bool:
        """
        Returns True if the API limit has been reached, False otherwise.

        If an exception occurred while getting the rate limit, this method returns True, assuming the limit has
        been reached.

        Additionally, implementations may print diagnostic information about the API limit.
        """
        return self.get_api_requests_left() in (0, None)

    @abstractmethod
    def create_pull_request(
        self,
        target_owner: str,
        target_repo: str,
        base_branch: str,
        head_branch: str,
        title: str,
        body: str,
    ) -> PullRequestDataValid:
        """
        Create a pull request from a forked repository. It is assumed that the forked repository is owned by the
        current user and has the same name as the target repository.
        :param target_owner: The owner of the target repository.
        :param target_repo: The name of the target repository.
        :param base_branch: The base branch of the pull request, located in the target repository.
        :param head_branch: The head branch of the pull request, located in the forked repository.
        :param title: The title of the pull request.
        :param body: The body of the pull request.
        :returns: The data of the created pull request.
        :raises GitPlatformError: If the pull request could not be created.
        :raises DuplicatePullRequestError: If a pull request already exists and the backend checks for it.
        """
        pass

    @abstractmethod
    def comment_on_pull_request(
        self, repo_owner: str, repo_name: str, pr_number: int, comment: str
    ) -> None:
        """
        Comment on an existing pull request.
        :param repo_owner: The owner of the repository.
        :param repo_name: The name of the repository.
        :param pr_number: The number of the pull request.
        :param comment: The comment to post.
        :raises RepositoryNotFoundError: If the repository does not exist.
        :raises GitPlatformError: If the comment could not be posted, including if the pull request does not exist.
        """
        pass


class _Github3SessionWrapper:
    """
    This is a wrapper around the github3.session.GitHubSession that allows us to intercept the response headers.
    """

    def __init__(self, session: GitHubSession):
        super().__init__()
        self._session = session
        self.last_response_headers: CaseInsensitiveDict[str] = CaseInsensitiveDict()

    def __getattr__(self, item):
        return getattr(self._session, item)

    def _forward_request(self, method, *args, **kwargs):
        response = method(*args, **kwargs)
        self.last_response_headers = copy.deepcopy(response.headers)
        return response

    def post(self, *args, **kwargs):
        return self._forward_request(self._session.post, *args, **kwargs)

    def get(self, *args, **kwargs):
        return self._forward_request(self._session.get, *args, **kwargs)


class GitHubBackend(GitPlatformBackend):
    """
    A git backend for GitHub, using both PyGithub and github3.py as clients.
    Both clients are used for historical reasons. In the future, this should be refactored to use only one client.

    Git operations are locked (globally) to prevent operations from interfering with each other.
    If this does impact performance too much, we can consider a per-repository locking strategy.
    """

    _GITHUB_PER_PAGE = 100
    """
    The number of items to fetch per page from the GitHub API.
    """

    def __init__(
        self, github3_client: github3.GitHub, pygithub_client: github.Github, token: str
    ):
        """
        Create a new GitHubBackend.
        Note: Because we need additional response headers, we wrap the github3 session of the github3 client
        with our own session wrapper and replace the github3 client's session with it.
        :param github3_client: The github3 client to use for interacting with the GitHub API.
        :param pygithub_client: The PyGithub client to use for interacting with the GitHub API.
        :param token: The token used for writing to git repositories. Note that you need to authenticate github3
        and PyGithub yourself. Use the `from_token` class method to create an instance
        that has all necessary clients set up.
        """
        cli = GitCli()
        super().__init__(cli)
        self.__token = token

        self.github3_client = github3_client
        self._github3_session = _Github3SessionWrapper(self.github3_client.session)
        self.github3_client.session = self._github3_session

        self.pygithub_client = pygithub_client

    @classmethod
    def from_token(cls, token: str):
        return cls(
            github3.login(token=token),
            github.Github(auth=github.Auth.Token(token), per_page=cls._GITHUB_PER_PAGE),
            token=token,
        )

    def _get_repo(self, owner: str, repo_name: str) -> None | github3.repos.Repository:
        try:
            repo = self.github3_client.repository(owner, repo_name)
        except github3.exceptions.NotFoundError:
            raise RepositoryNotFoundError(
                f"Repository {owner}/{repo_name} does not exist."
            )
        except Exception as e:
            logger.warning(
                f"GitHub API error fetching repo {owner}/{repo_name}.",
                exc_info=e,
            )
            raise e

        return repo

    def does_repository_exist(self, owner: str, repo_name: str) -> bool:
        try:
            self._get_repo(owner, repo_name)
            return True
        except RepositoryNotFoundError:
            return False

    @lock_git_operation()
    def push_to_repository(
        self, owner: str, repo_name: str, git_dir: Path, branch: str
    ):
        # We add the token and remove it immediately after pushing as an additional defense-in-depth measure.
        try:
            self.cli.add_token(git_dir, self.GIT_PLATFORM_ORIGIN, self.__token)

            remote_url = self.get_remote_url(
                owner,
                repo_name,
                GitConnectionMode.HTTPS,
            )
            self.cli.push_to_url(git_dir, remote_url, branch)
        finally:
            self.cli.clear_token(git_dir, self.GIT_PLATFORM_ORIGIN)

    @lock_git_operation()
    def fork(self, owner: str, repo_name: str):
        if self.does_repository_exist(self.user, repo_name):
            # The fork already exists, so we only sync the default branch.
            self._sync_default_branch(owner, repo_name)
            return

        repo = self._get_repo(owner, repo_name)

        logger.debug(f"Forking {owner}/{repo_name}.")
        repo.create_fork()

        # Sleep to make sure the fork is created before we go after it
        time.sleep(5)

    @lock_git_operation()
    def _sync_default_branch(self, upstream_owner: str, repo_name: str):
        fork_owner = self.user

        upstream_repo = self.pygithub_client.get_repo(f"{upstream_owner}/{repo_name}")
        fork = self.pygithub_client.get_repo(f"{fork_owner}/{repo_name}")

        if upstream_repo.default_branch == fork.default_branch:
            return

        logger.info(
            f"Syncing default branch of {fork_owner}/{repo_name} with {upstream_owner}/{repo_name}..."
        )

        fork.rename_branch(fork.default_branch, upstream_repo.default_branch)

        # Sleep to wait for branch name change
        time.sleep(5)

    @cached_property
    def user(self) -> str:
        return self.pygithub_client.get_user().login

    def get_api_requests_left(self) -> int | None:
        try:
            limit_info = self.github3_client.rate_limit()
        except github3.exceptions.GitHubException as e:
            logger.warning("GitHub API error while fetching rate limit.", exc_info=e)
            return None

        try:
            core_resource = limit_info["resources"]["core"]
            remaining_limit = core_resource["remaining"]
        except KeyError as e:
            logger.warning("GitHub API error while parsing rate limit.", exc_info=e)
            return None

        if remaining_limit != 0:
            return remaining_limit

        # try to log when the limit will be reset
        try:
            reset_timestamp = core_resource["reset"]
        except KeyError as e:
            logger.warning(
                "GitHub API error while fetching rate limit reset time.",
                exc_info=e,
            )
            return remaining_limit

        logger.info(
            "GitHub API limit reached, will reset at "
            f"{datetime.utcfromtimestamp(reset_timestamp).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )

        return remaining_limit

    def create_pull_request(
        self,
        target_owner: str,
        target_repo: str,
        base_branch: str,
        head_branch: str,
        title: str,
        body: str,
    ) -> PullRequestDataValid:
        repo: github3.repos.Repository = self.github3_client.repository(
            target_owner, target_repo
        )

        try:
            response: github3.pulls.ShortPullRequest | None = repo.create_pull(
                title=title,
                base=base_branch,
                head=f"{self.user}:{head_branch}",
                body=body,
            )
        except github3.exceptions.UnprocessableEntity as e:
            if any("already exists" in error.get("message", "") for error in e.errors):
                raise DuplicatePullRequestError(
                    f"Pull request from {self.user}:{head_branch} to {target_owner}:{base_branch} already exists."
                ) from e
            raise

        if response is None:
            raise GitPlatformError("Could not create pull request.")

        # fields like ETag and Last-Modified are stored in the response headers, we need to extract them
        header_fields = {
            k: self._github3_session.last_response_headers[k]
            for k in PullRequestDataValid.HEADER_FIELDS
        }

        # note: this ignores extra fields in the response
        return PullRequestDataValid.model_validate(response.as_dict() | header_fields)

    def comment_on_pull_request(
        self, repo_owner: str, repo_name: str, pr_number: int, comment: str
    ) -> None:
        try:
            repo = self.github3_client.repository(repo_owner, repo_name)
        except github3.exceptions.NotFoundError:
            raise RepositoryNotFoundError(
                f"Repository {repo_owner}/{repo_name} not found."
            )

        try:
            pr = repo.pull_request(pr_number)
        except github3.exceptions.NotFoundError:
            raise GitPlatformError(
                f"Pull request {repo_owner}/{repo_name}#{pr_number} not found."
            )

        try:
            pr.create_comment(comment)
        except github3.GitHubError:
            raise GitPlatformError(
                f"Could not comment on pull request {repo_owner}/{repo_name}#{pr_number}."
            )


class DryRunBackend(GitPlatformBackend):
    """
    A git backend that doesn't modify anything and only relies on public APIs that do not require authentication.
    Useful for local testing with dry-run.

    By default, the dry run backend assumes that the current user has not created any forks yet.
    If forks are created, their names are stored in memory and can be checked with `does_repository_exist`.
    """

    _USER = "auto-tick-bot-dry-run"

    def __init__(self):
        super().__init__(GitCli())
        self._repos: dict[str, str] = {}
        """
        _repos maps from repository name to the owner of the upstream repository.
        If a remote URL of a fork is requested with get_remote_url, _USER (the virtual current user) is
        replaced by the owner of the upstream repository. This allows cloning the forked repository.
        """

    def get_api_requests_left(self) -> Bound:
        return Bound.INFINITY

    def does_repository_exist(self, owner: str, repo_name: str) -> bool:
        if owner == self._USER:
            return repo_name in self._repos

        # We do not use the GitHub API because unauthenticated requests are quite strictly rate-limited.
        return self.cli.does_remote_exist(
            self.get_remote_url(owner, repo_name, GitConnectionMode.HTTPS)
        )

    def get_remote_url(
        self,
        owner: str,
        repo_name: str,
        connection_mode: GitConnectionMode = GitConnectionMode.HTTPS,
    ) -> str:
        if owner != self._USER:
            return super().get_remote_url(owner, repo_name, connection_mode)
        # redirect to the upstream repository
        try:
            upstream_owner = self._repos[repo_name]
        except KeyError:
            raise RepositoryNotFoundError(
                f"Repository {owner}/{repo_name} appears to be a virtual fork but does not exist. Note that dry-run "
                "forks are persistent only for the duration of the backend instance."
            )

        return super().get_remote_url(upstream_owner, repo_name, connection_mode)

    def push_to_repository(
        self, owner: str, repo_name: str, git_dir: Path, branch: str
    ):
        logger.debug(
            f"Dry Run: Pushing changes from {git_dir} to {owner}/{repo_name} on branch {branch}."
        )

    def fork(self, owner: str, repo_name: str):
        if repo_name in self._repos:
            logger.debug(f"Fork of {repo_name} already exists. Doing nothing.")
            return

        if not self.does_repository_exist(owner, repo_name):
            raise RepositoryNotFoundError(
                f"Cannot fork non-existing repository {owner}/{repo_name}."
            )

        logger.debug(
            f"Dry Run: Creating fork of {owner}/{repo_name} for user {self._USER}."
        )
        self._repos[repo_name] = owner

    def _sync_default_branch(self, upstream_owner: str, upstream_repo: str):
        logger.debug(
            f"Dry Run: Syncing default branch of {upstream_owner}/{upstream_repo}."
        )

    @property
    def user(self) -> str:
        return self._USER

    @staticmethod
    def print_dry_run_message(title: str, data: dict[str, str]):
        """
        Print a dry run output message.
        :param title: The title of the message.
        :param data: The data to print. The keys are the field names and the values are the field values.
        Please capitalize the keys for consistency.
        """
        border = "=============================================================="
        output = textwrap.dedent(
            f"""
            {border}
            Dry Run: {title}"""
        )

        def format_field(key: str, value: str) -> str:
            if "\n" in value:
                return f"{key}:\n{value}"
            return f"{key}: {value}"

        output += "".join(format_field(key, value) for key, value in data.items())
        output += f"\n{border}"

        logger.debug(output)

    def create_pull_request(
        self,
        target_owner: str,
        target_repo: str,
        base_branch: str,
        head_branch: str,
        title: str,
        body: str,
    ) -> PullRequestDataValid:
        self.print_dry_run_message(
            "Create Pull Request",
            {
                "Title": f'"{title}"',
                "Target Repository": f"{target_owner}/{target_repo}",
                "Branches": f"{self.user}:{head_branch} -> {target_owner}:{base_branch}",
                "Body": body,
            },
        )

        now = datetime.now()
        return PullRequestDataValid.model_validate(
            {
                "ETag": "GITHUB_PR_ETAG",
                "Last-Modified": utils.format_datetime(now),
                "id": 13371337,
                "html_url": f"https://github.com/{target_owner}/{target_repo}/pulls/1337",
                "created_at": now,
                "mergeable_state": GithubPullRequestMergeableState.CLEAN,
                "mergeable": True,
                "merged": False,
                "draft": False,
                "number": 1337,
                "state": PullRequestState.OPEN,
                "head": PullRequestInfoHead(ref=head_branch),
                "base": GithubPullRequestBase(repo=GithubRepository(name=target_repo)),
            }
        )

    def comment_on_pull_request(
        self, repo_owner: str, repo_name: str, pr_number: int, comment: str
    ):
        if not self.does_repository_exist(repo_owner, repo_name):
            raise RepositoryNotFoundError(
                f"Repository {repo_owner}/{repo_name} not found."
            )

        self.print_dry_run_message(
            "Comment on Pull Request",
            {
                "Pull Request": f"{repo_owner}/{repo_name}#{pr_number}",
                "Comment": comment,
            },
        )


def github_backend() -> GitHubBackend:
    """
    This helper method will be removed in the future, use the GitHubBackend class directly.
    """
    return GitHubBackend.from_token(get_bot_token())


def is_github_api_limit_reached() -> bool:
    """
    Return True if the GitHub API limit has been reached, False otherwise.

    This method will be removed in the future, use the GitHubBackend class directly.
    """
    backend = github_backend()

    return backend.is_api_limit_reached()


@lock_git_operation()
def delete_branch(pr_json: LazyJson, dry_run: bool = False) -> None:
    ref = pr_json["head"]["ref"]
    if dry_run:
        print(f"dry run: deleting ref {ref}")
        return
    name = pr_json["base"]["repo"]["name"]

    gh = github3_client()
    deploy_repo = gh.me().login + "/" + name

    token = get_bot_token()

    run_command_hiding_token(
        [
            "git",
            "push",
            f"https://{token}@github.com/{deploy_repo}.git",
            "--delete",
            ref,
        ],
        token=token,
    )
    # Replace ref so we know not to try again
    pr_json["head"]["ref"] = "this_is_not_a_branch"


def trim_pr_json_keys(
    pr_json: Union[Dict, LazyJson],
    src_pr_json: Optional[Union[Dict, LazyJson]] = None,
) -> Union[Dict, LazyJson]:
    """Trim the set of keys in the PR json. The keys kept are defined by the global
    PR_KEYS_TO_KEEP.

    Parameters
    ----------
    pr_json : dict-like
        A dict-like object with the current PR information.
    src_pr_json : dict-like, optional
        If this object is sent, the values for the trimmed keys are taken
        from this object. Otherwise `pr_json` is used for the values.

    Returns
    -------
    pr_json : dict-like
        A dict-like object with the current PR information trimmed to the subset of
        keys.
    """

    # keep a subset of keys
    def _munge_dict(dest, src, keys):
        for k, v in keys.items():
            if k in src:
                if v is None:
                    dest[k] = src[k]
                else:
                    dest[k] = {}
                    _munge_dict(dest[k], src[k], v)

    if src_pr_json is None:
        src_pr_json = copy.deepcopy(dict(pr_json))

    pr_json.clear()
    _munge_dict(pr_json, src_pr_json, PR_KEYS_TO_KEEP)
    return pr_json


def lazy_update_pr_json(
    pr_json: Union[Dict, LazyJson], force: bool = False
) -> Union[Dict, LazyJson]:
    """Lazily update a GitHub PR.

    This function will use the ETag in the GitHub API to update PR information
    lazily. It sends the ETag to github properly and if nothing is changed on their
    end, it simply returns the PR. Otherwise the information is refreshed.

    Parameters
    ----------
    pr_json : dict-like
        A dict-like object with the current PR information.
    force : bool, optional
        If True, forcibly update the PR json even if it is not out of date
        according to the ETag. Default is False.

    Returns
    -------
    pr_json : dict-like
        A dict-like object with the current PR information.
    """
    hdrs = {
        "Authorization": f"token {get_bot_token()}",
        "Accept": "application/vnd.github.v3+json",
    }
    if not force and "ETag" in pr_json:
        hdrs["If-None-Match"] = pr_json["ETag"]

    if "repo" not in pr_json["base"] or (
        "repo" in pr_json["base"] and "name" not in pr_json["base"]["repo"]
    ):
        # some pr json blobs never had this key so we backfill
        repo_name = pr_json["html_url"].split("/conda-forge/")[1]
        if repo_name[-1] == "/":
            repo_name = repo_name[:-1]
        if "repo" not in pr_json["base"]:
            pr_json["base"]["repo"] = {}
        pr_json["base"]["repo"]["name"] = repo_name

    if "/pull/" in pr_json["base"]["repo"]["name"]:
        pr_json["base"]["repo"]["name"] = pr_json["base"]["repo"]["name"].split(
            "/pull/",
        )[0]

    r = requests.get(
        "https://api.github.com/repos/conda-forge/"
        f"{pr_json['base']['repo']['name']}/pulls/{pr_json['number']}",
        headers=hdrs,
    )

    if r.status_code == 200:
        pr_json = trim_pr_json_keys(pr_json, src_pr_json=r.json())
        pr_json["ETag"] = r.headers["ETag"]
        pr_json["Last-Modified"] = r.headers["Last-Modified"]
    else:
        pr_json = trim_pr_json_keys(pr_json)

    return pr_json


@backoff.on_exception(
    backoff.expo,
    (RequestException, Timeout),
    max_time=MAX_GITHUB_TIMEOUT,
)
def refresh_pr(
    pr_json: LazyJson,
    dry_run: bool = False,
) -> Optional[dict]:
    if pr_json["state"] != "closed":
        if dry_run:
            print("dry run: refresh pr %s" % pr_json["id"])
            pr_dict = dict(pr_json)
        else:
            pr_json = lazy_update_pr_json(copy.deepcopy(pr_json))

            # if state passed from opened to merged or if it
            # closed for a day delete the branch
            if pr_json["state"] == "closed" and pr_json.get("merged_at", False):
                delete_branch(pr_json=pr_json, dry_run=dry_run)
            pr_dict = dict(pr_json)

        return pr_dict

    return None


def get_pr_obj_from_pr_json(
    pr_json: Union[Dict, LazyJson],
    gh: github3.GitHub,
) -> github3.pulls.PullRequest:
    """Produce a github3 pull request object from pr_json.

    Parameters
    ----------
    pr_json : dict-like
        A dict-like object with the current PR information.
    gh : github3 object
        The github3 object for interacting with the GitHub API.

    Returns
    -------
    pr_obj : github3.pulls.PullRequest
        The pull request object.
    """
    feedstock_reponame = pr_json["base"]["repo"]["name"]
    repo = gh.repository("conda-forge", feedstock_reponame)
    return repo.pull_request(pr_json["number"])


@backoff.on_exception(
    backoff.expo,
    (RequestException, Timeout),
    max_time=MAX_GITHUB_TIMEOUT,
)
def close_out_labels(
    pr_json: LazyJson,
    dry_run: bool = False,
) -> Optional[dict]:
    gh = github3_client()

    # run this twice so we always have the latest info (eg a thing was already closed)
    if pr_json["state"] != "closed" and "bot-rerun" in [
        lab["name"] for lab in pr_json.get("labels", [])
    ]:
        # update
        if dry_run:
            print("dry run: checking pr %s" % pr_json["id"])
        else:
            pr_json = lazy_update_pr_json(pr_json)

    if pr_json["state"] != "closed" and "bot-rerun" in [
        lab["name"] for lab in pr_json.get("labels", [])
    ]:
        if dry_run:
            print("dry run: comment and close pr %s" % pr_json["id"])
        else:
            pr_obj = get_pr_obj_from_pr_json(pr_json, gh)
            pr_obj.create_comment(
                "Due to the `bot-rerun` label I'm closing "
                "this PR. I will make another one as"
                f" appropriate. This message was generated by {get_bot_run_url()} - please use this URL for debugging.",
            )
            pr_obj.close()

            delete_branch(pr_json=pr_json, dry_run=dry_run)
            pr_json = lazy_update_pr_json(pr_json)

        return dict(pr_json)

    return None


def close_out_dirty_prs(
    pr_json: LazyJson,
    dry_run: bool = False,
) -> Optional[dict]:
    gh = github3_client()

    # run this twice so we always have the latest info (eg a thing was already closed)
    if pr_json["state"] != "closed" and pr_json["mergeable_state"] == "dirty":
        # update
        if dry_run:
            print("dry run: checking pr %s" % pr_json["id"])
        else:
            pr_json = lazy_update_pr_json(pr_json)

    if (
        pr_json["state"] != "closed"
        and pr_json["mergeable_state"] == "dirty"
        and not pr_json.get("draft", False)
    ):
        d = dict(pr_json)

        if dry_run:
            print("dry run: comment and close pr %s" % pr_json["id"])
        else:
            pr_obj = get_pr_obj_from_pr_json(pr_json, gh)

            if all(
                c.as_dict()["commit"]["author"]["name"] in CF_BOT_NAMES
                for c in pr_obj.commits()
            ):
                pr_obj.create_comment(
                    "I see that this PR has conflicts, and I'm the only committer. "
                    "I'm going to close this PR and will make another one as"
                    f" appropriate. This was generated by {get_bot_run_url()} - "
                    "please use this URL for debugging,",
                )
                pr_obj.close()

                delete_branch(pr_json=pr_json, dry_run=dry_run)

                pr_json = lazy_update_pr_json(pr_json)
                d = dict(pr_json)

                # This will cause the _update_nodes_with_bot_rerun to trigger
                # properly and shouldn't be overridden since
                # this is the last function to run, the long term solution here
                # is to add the bot to conda-forge and then
                # it should have label adding capability and we can just add
                # the label properly
                d["labels"].append(BOT_RERUN_LABEL)

        return d

    return None
