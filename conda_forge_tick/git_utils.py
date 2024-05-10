"""Utilities for managing github repos"""

import copy
import enum
import logging
import math
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Dict, Literal, Optional, Tuple, Union

import backoff
import github
import github3
import github3.exceptions
import github3.pulls
import github3.repos
import requests
from doctr.travis import run_command_hiding_token as doctr_run
from requests.exceptions import RequestException, Timeout

from conda_forge_tick import sensitive_env

# TODO: handle the URLs more elegantly (most likely make this a true library
# and pull all the needed info from the various source classes)
from conda_forge_tick.lazy_json_backends import LazyJson

from .contexts import FeedstockContext
from .os_utils import pushd
from .utils import get_bot_run_url

logger = logging.getLogger(__name__)

backoff._decorator._is_event_loop = lambda: False

GITHUB3_CLIENT = threading.local()
GITHUB_CLIENT = threading.local()

MAX_GITHUB_TIMEOUT = 60

GIT_CLONE_DIR = "./feedstocks/"

BOT_RERUN_LABEL = {
    "name": "bot-rerun",
}

CF_BOT_NAMES = {"regro-cf-autotick-bot", "conda-forge-linter"}

# these keys are kept from github PR json blobs
# to add more keys to keep, put them in the right spot in the dict and
# set them to None. Also add them to the PullRequestInfo Pydantic model!
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


def github3_client() -> github3.GitHub:
    """
    This will be removed in the future, use the GitHubBackend class instead.
    """
    if not hasattr(GITHUB3_CLIENT, "client"):
        with sensitive_env() as env:
            GITHUB3_CLIENT.client = github3.login(token=env["BOT_TOKEN"])
    return GITHUB3_CLIENT.client


def github_client() -> github.Github:
    """
    This will be removed in the future, use the GitHubBackend class instead.
    """
    if not hasattr(GITHUB_CLIENT, "client"):
        with sensitive_env() as env:
            GITHUB_CLIENT.client = github.Github(
                auth=github.Auth.Token(env["BOT_TOKEN"]),
                per_page=100,
            )
    return GITHUB_CLIENT.client


class Bound(float, enum.Enum):
    def __str__(self):
        return str(self.value)

    INFINITY = math.inf
    """
    Python does not have support for a literal infinity value, so we use this enum for it.
    """


class GitConnectionMode(enum.StrEnum):
    SSH = "ssh"
    HTTPS = "https"


class GitCliError(Exception):
    pass


class RepositoryNotFoundError(Exception):
    """
    Raised when a repository is not found.
    """

    pass


class _GitCli:
    """
    A simple wrapper around the git command line interface.
    """

    @staticmethod
    def _run_git_command(
        cmd: list[str | Path],
        working_directory: Path | None = None,
        check_error: bool = True,
    ) -> subprocess.CompletedProcess:
        """
        Run a git command.
        :param cmd: The command to run, as a list of strings.
        :param working_directory: The directory to run the command in. If None, the command will be run in the current
        working directory.
        :param check_error: If True, raise a GitCliError if the git command fails.
        :return: The result of the git command.
        """
        git_command = ["git"] + cmd

        logger.debug(f"Running git command: {git_command}")

        try:
            return subprocess.run(git_command, check=check_error, cwd=working_directory)
        except subprocess.CalledProcessError as e:
            raise GitCliError("Error running git command.") from e

    def reset_hard(self, git_dir: Path, to_treeish: str = "HEAD"):
        """
        Reset the git index of a directory to the state of the last commit with `git reset --hard HEAD`.
        :param git_dir: The directory to reset.
        :param to_treeish: The treeish to reset to. Defaults to "HEAD".
        :raises GitCliError: If the git command fails.
        """
        self._run_git_command(["reset", "--quiet", "--hard", to_treeish], git_dir)

    def clone_repo(self, origin_url: str, target_dir: Path):
        """
        Clone a Git repository. If target_dir already exists, it will be reset to the state of the git index
        with `git reset --hard HEAD`. This may be unexpected behavior because target_dir could contain a
        different repository. Use with caution.
        :param target_dir: The directory to clone the repository into.
        :param origin_url: The URL of the repository to clone.
        :raises GitCliError: If the git command fails.
        """
        if target_dir.exists():
            self.reset_hard(target_dir)
            return
        try:
            self._run_git_command(["clone", "--quiet", origin_url, target_dir])
        except GitCliError as e:
            raise GitCliError(
                f"Error cloning repository from {origin_url}. Does the repository exist?"
            ) from e

    def add_remote(self, remote_name: str, remote_url: str, git_dir: Path):
        """
        Add a remote to a git repository.
        :param remote_name: The name of the remote.
        :param remote_url: The URL of the remote.
        :param git_dir: The directory of the git repository.
        :raises GitCliError: If the git command fails (e.g., the remote already exists).
        """
        self._run_git_command(["remote", "add", remote_name, remote_url], git_dir)

    def fetch_all(self, git_dir: Path):
        """
        Fetch all changes from all remotes.
        :param git_dir: The directory of the git repository.
        :raises GitCliError: If the git command fails.
        """
        self._run_git_command(["fetch", "--all", "--quiet"], git_dir)

    def does_branch_exist(self, branch_name: str, git_dir: Path):
        """
        Check if a branch exists in a git repository.
        :param branch_name: The name of the branch.
        :param git_dir: The directory of the git repository.
        :return: True if the branch exists, False otherwise.
        :raises GitCliError: If the git command fails.
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
        :param remote_url: The URL of the remote.
        :return: True if the remote exists, False otherwise.
        """
        ret = self._run_git_command(["ls-remote", remote_url], check_error=False)

        return ret.returncode == 0

    def checkout_branch(
        self,
        branch: str,
        git_dir: Path,
        create_branch_name: str | None = False,
        track: bool = False,
    ):
        """
        Checkout a branch in a git repository.
        :param branch: The branch to check out.
        :param git_dir: The directory of the git repository.
        :param create_branch_name: If set, create a new branch with the given name starting at branch_name
        (using the -b option).
        :param track: If True, set the branch to track the remote branch with the same name (sets the --track flag).
        If create_branch_name is not set, a new branch will be created with the name inferred from branch_name.
        For example, if branch_name is "upstream/main", the new branch will be "main".
        :raises GitCliError: If the git command fails.
        """
        create_branch_option = ["-b", create_branch_name] if create_branch_name else []
        track_flag = ["--track"] if track else []
        self._run_git_command(
            ["checkout", "--quiet"] + create_branch_option + track_flag + [branch],
            git_dir,
        )

    def clone_fork_and_branch_custom_url(
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
        self.clone_repo(origin_url, target_dir)

        try:
            self.add_remote("upstream", upstream_url, target_dir)
        except GitCliError as e:
            logger.debug(
                "It looks like remote 'upstream' already exists. Ignoring.", exc_info=e
            )
            pass

        self.fetch_all(target_dir)

        if self.does_branch_exist(base_branch, target_dir):
            self.checkout_branch(base_branch, target_dir)
        else:
            try:
                self.checkout_branch(f"upstream/{base_branch}", target_dir, track=True)
            except GitCliError as e:
                logger.debug(
                    "Could not check out with git checkout --track. Trying git checkout -b.",
                    exc_info=e,
                )

                # not sure why this is needed, but it was in the original code
                self.checkout_branch(
                    f"upstream/{base_branch}",
                    target_dir,
                    create_branch_name=base_branch,
                )

        # not sure why this is needed, but it was in the original code
        self.reset_hard(target_dir, f"upstream/{base_branch}")

        try:
            logger.debug(
                f"Trying to checkout branch {new_branch} without creating a new branch"
            )
            self.checkout_branch(new_branch, target_dir)
        except GitCliError:
            logger.debug(
                f"It seems branch {new_branch} does not exist. Creating it.",
            )
            self.checkout_branch(base_branch, target_dir, create_branch_name=new_branch)


class GitBackend(_GitCli, ABC):
    """
    A backend for interacting with a git repository, and a platform around it (e.g. GitHub).
    Note that this class is not thread-safe, you should create a new instance for each thread.

    Implementation Note: If you wonder what should be in this class vs. the _GitCli class, the GitBackend class should
    contain the logic for interacting with the platform (e.g. GitHub), while the _GitCli class should contain the logic
    for interacting with the git repository itself. If you need to know anything specific about the platform,
    it should be in the GitBackend class.
    """

    @abstractmethod
    def does_repository_exist(self, owner: str, repo_name: str) -> bool:
        """
        Check if a repository exists.
        :param owner: The owner of the repository.
        :param repo_name: The name of the repository.
        """
        pass

    @staticmethod
    def get_remote_url(
        owner: str,
        repo_name: str,
        connection_mode: GitConnectionMode = GitConnectionMode.SSH,
    ) -> str:
        """
        Using SSH as the default protocol, get the URL of the remote repository.
        :param owner: The owner of the repository.
        :param repo_name: The name of the repository.
        :param connection_mode: The connection mode to use.
        :raises ValueError: If the connection mode is not supported.
        """
        # Currently we don't need any abstraction for other platforms than GitHub, so we don't build such abstractions.
        match connection_mode:
            case GitConnectionMode.HTTPS:
                return f"https://github.com/{owner}/{repo_name}.git"
            case GitConnectionMode.SSH:
                return f"git@github.com:{owner}/{repo_name}.git"
            case _:
                raise ValueError(f"Unsupported connection mode: {connection_mode}")

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

    def clone_fork_and_branch(
        self,
        upstream_owner: str,
        repo_name: str,
        target_dir: Path,
        new_branch: str,
        base_branch: str = "main",
    ):
        """
        Identical to `clone_fork_and_branch_custom_url`, but generates the URLs from the repository name.

        :param upstream_owner: The owner of the upstream repository.
        :param repo_name: The name of the repository.
        :param target_dir: The directory to clone the repository into.
        :param new_branch: The name of the branch to create.
        :param base_branch: The name of the base branch to branch from.

        :raises GitCliError: If a git command fails.
        """
        self.clone_fork_and_branch_custom_url(
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


class GitHubBackend(GitBackend):
    """
    A git backend for GitHub, using both PyGithub and github3.py as clients.
    It is unclear why both clients are used, in the future, this should be refactored to use only one client.
    Note that this class is not thread-safe, you should create a new instance for each thread.
    """

    _GITHUB_PER_PAGE = 100
    """
    The number of items to fetch per page from the GitHub API.
    """

    def __init__(self, github3_client: github3.GitHub, pygithub_client: github.Github):
        self.github3_client = github3_client
        self.pygithub_client = pygithub_client

    @classmethod
    def from_token(cls, token: str):
        return cls(
            github3.login(token=token),
            github.Github(auth=github.Auth.Token(token), per_page=cls._GITHUB_PER_PAGE),
        )

    def does_repository_exist(self, owner: str, repo_name: str) -> bool:
        repo = self.github3_client.repository(owner, repo_name)
        return repo is not None

    def fork(self, owner: str, repo_name: str):
        if self.does_repository_exist(self.user, repo_name):
            # The fork already exists, so we only sync the default branch.
            self._sync_default_branch(owner, repo_name)
            return

        repo = self.github3_client.repository(owner, repo_name)
        if repo is None:
            raise RepositoryNotFoundError(
                f"Repository {owner}/{repo_name} does not exist."
            )

        logger.debug(f"Forking {owner}/{repo_name}.")
        repo.create_fork()

        # Sleep to make sure the fork is created before we go after it
        time.sleep(5)

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


class DryRunBackend(GitBackend):
    """
    A git backend that doesn't modify anything and only relies on public APIs that do not require authentication.
    Useful for local testing with dry-run.
    Note that this class is not thread-safe, you should create a new instance for each thread.
    """

    _USER = "virtual-dry-run-user"

    def __init__(self):
        self._repos: set[str] = set()

    def get_api_requests_left(self) -> Bound:
        return Bound.INFINITY

    def does_repository_exist(self, owner: str, repo_name: str) -> bool:
        if owner == self._USER:
            return repo_name in self._repos

        # We do not use the GitHub API because unauthenticated requests are quite strictly rate-limited.
        return self.does_remote_exist(self.get_remote_url(owner, repo_name))

    def fork(self, owner: str, repo_name: str):
        if repo_name in self._repos:
            raise ValueError(f"Fork of {repo_name} already exists.")

        logger.debug(
            f"Dry Run: Creating fork of {owner}/{repo_name} for user {self._USER}."
        )
        self._repos.add(repo_name)

    def _sync_default_branch(self, upstream_owner: str, upstream_repo: str):
        logger.debug(
            f"Dry Run: Syncing default branch of {upstream_owner}/{upstream_repo}."
        )

    def user(self) -> str:
        return self._USER


def github_backend() -> GitHubBackend:
    """
    This helper method will be removed in the future, use the GitHubBackend class directly.
    """
    with sensitive_env() as env:
        return GitHubBackend.from_token(env["BOT_TOKEN"])


def feedstock_url(fctx: FeedstockContext, protocol: str = "ssh") -> str:
    """Returns the URL for a conda-forge feedstock."""
    feedstock = fctx.feedstock_name + "-feedstock"
    if feedstock.startswith("http://github.com/"):
        return feedstock
    elif feedstock.startswith("https://github.com/"):
        return feedstock
    elif feedstock.startswith("git@github.com:"):
        return feedstock
    protocol = protocol.lower()
    if protocol == "http":
        url = "http://github.com/conda-forge/" + feedstock + ".git"
    elif protocol == "https":
        url = "https://github.com/conda-forge/" + feedstock + ".git"
    elif protocol == "ssh":
        url = "git@github.com:conda-forge/" + feedstock + ".git"
    else:
        msg = f"Unrecognized github protocol {protocol}, must be ssh, http, or https."
        raise ValueError(msg.format(protocol))
    return url


def feedstock_repo(fctx: FeedstockContext) -> str:
    """Gets the name of the feedstock repository."""
    return fctx.feedstock_name + "-feedstock"


def fork_url(feedstock_url: str, username: str) -> str:
    """Creates the URL of the user's fork."""
    beg, end = feedstock_url.rsplit("/", 1)
    beg = beg[:-11]  # chop off 'conda-forge'
    url = beg + username + "/" + end
    return url


def get_repo(
    fctx: FeedstockContext,
    branch: str,
    base_branch: str = "main",
) -> Tuple[str, github3.repos.Repository] | Tuple[Literal[False], Literal[False]]:
    """Get the feedstock repo

    Parameters
    ----------
    fctx : FeedstockContext
        Feedstock context used for constructing feedstock urls, etc.
    branch : str
        The branch to be made.
    protocol : str, optional
        The git protocol to use, defaults to ``ssh``
    pull_request : bool, optional
        If true issue pull request, defaults to true
    fork : bool
        If true create a fork, defaults to true
    base_branch : str, optional
        The base branch from which to make the new branch.

    Returns
    -------
    recipe_dir : str
        The recipe directory
    repo : github3 repository
        The github3 repository object.
    """
    backend = github_backend()
    feedstock_repo_name = feedstock_repo(fctx)

    try:
        backend.fork("conda-forge", feedstock_repo_name)
    except RepositoryNotFoundError:
        logger.warning(f"Could not fork conda-forge/{feedstock_repo_name}")
        with fctx.attrs["pr_info"] as pri:
            pri["bad"] = f"{fctx.package_name}: does not match feedstock name\n"
        return False, False

    feedstock_dir = Path(GIT_CLONE_DIR) / (fctx.package_name + "-feedstock")

    backend.clone_fork_and_branch(
        upstream_owner="conda-forge",
        repo_name=feedstock_repo_name,
        target_dir=feedstock_dir,
        new_branch=branch,
        base_branch=base_branch,
    )

    # This is needed because we want to migrate to the new backend step-by-step
    repo: github3.repos.Repository | None = github3_client().repository(
        "conda-forge", feedstock_repo_name
    )

    assert repo is not None

    return feedstock_repo_name, repo


def delete_branch(pr_json: LazyJson, dry_run: bool = False) -> None:
    ref = pr_json["head"]["ref"]
    if dry_run:
        print(f"dry run: deleting ref {ref}")
        return
    name = pr_json["base"]["repo"]["name"]

    gh = github3_client()
    deploy_repo = gh.me().login + "/" + name

    with sensitive_env() as env:
        doctr_run(
            [
                "git",
                "push",
                f"https://{env['BOT_TOKEN']}@github.com/{deploy_repo}.git",
                "--delete",
                ref,
            ],
            token=env["BOT_TOKEN"].encode("utf-8"),
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
    end, it simply returns the PR. Otherwise the information is refershed.

    Parameters
    ----------
    pr_json : dict-like
        A dict-like object with the current PR information.
    force : bool, optional
        If True, forcibly update the PR json even if it is not out of date
        according to the ETag. Default is False.
    trim : bool, optional
        If True, trim the PR json keys to ones in the global PR_KEYS_TO_KEEP.
        Default is True.

    Returns
    -------
    pr_json : dict-like
        A dict-like object with the current PR information.
    """
    with sensitive_env() as env:
        hdrs = {
            "Authorization": f"token {env['BOT_TOKEN']}",
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


def push_repo(
    fctx: FeedstockContext,
    feedstock_dir: str,
    body: str,
    repo: github3.repos.Repository,
    title: str,
    branch: str,
    base_branch: str = "main",
    head: Optional[str] = None,
    dry_run: bool = False,
) -> Union[dict, bool, None]:
    """Push a repo up to github

    Parameters
    ----------
    fctx : FeedstockContext
        Feedstock context used for constructing feedstock urls, etc.
    feedstock_dir : str
        The feedstock directory
    body : str
        The PR body.
    repo : github3.repos.Repository
        The feedstock repo as a github3 object.
    title : str
        The title of the PR.
    head : str, optional
        The github head for the PR in the form `username:branch`.
    branch : str
        The head branch of the PR.
    base_branch : str, optional
        The base branch or target branch of the PR.

    Returns
    -------
    pr_json: dict
        The dict representing the PR, can be used with `from_json`
        to create a PR instance.
    """
    with sensitive_env() as env, pushd(feedstock_dir):
        # Setup push from doctr
        # Copyright (c) 2016 Aaron Meurer, Gil Forsyth
        token = env["BOT_TOKEN"]
        gh_username = github3_client().me().login

        if head is None:
            head = gh_username + ":" + branch

        deploy_repo = gh_username + "/" + fctx.feedstock_name + "-feedstock"
        if dry_run:
            repo_url = f"https://github.com/{deploy_repo}.git"
            print(f"dry run: adding remote and pushing up branch for {repo_url}")
        else:
            ecode = doctr_run(
                [
                    "git",
                    "remote",
                    "add",
                    "regro_remote",
                    f"https://{token}@github.com/{deploy_repo}.git",
                ],
                token=token.encode("utf-8"),
            )
            if ecode != 0:
                print("Failed to add git remote!")
                return False

            ecode = doctr_run(
                ["git", "push", "--set-upstream", "regro_remote", branch],
                token=token.encode("utf-8"),
            )
            if ecode != 0:
                print("Failed to push to remote!")
                return False

    # lastly make a PR for the feedstock
    print("Creating conda-forge feedstock pull request...")
    if dry_run:
        print(f"dry run: create pr with title: {title}")
        return False
    else:
        pr = repo.create_pull(title, base_branch, head, body=body)
        if pr is None:
            print("Failed to create pull request!")
            return False
        else:
            print("Pull request created at " + pr.html_url)

    # Return a json object so we can remake the PR if needed
    pr_dict: dict = pr.as_dict()

    return trim_pr_json_keys(pr_dict)


def comment_on_pr(pr_json, comment, repo):
    """Make a comment on a PR.

    Parameters
    ----------
    pr_json : dict
        A dict-like json blob with the PR information
    comment : str
        The comment to make.
    repo : github3.repos.Repository
        The feedstock repo as a github3 object.
    """
    pr_obj = repo.pull_request(pr_json["number"])
    pr_obj.create_comment(comment)


@backoff.on_exception(
    backoff.expo,
    (RequestException, Timeout),
    max_time=MAX_GITHUB_TIMEOUT,
)
def ensure_label_exists(
    repo: github3.repos.Repository,
    label_dict: dict,
    dry_run: bool = False,
) -> None:
    if dry_run:
        print(f"dry run: ensure label exists {label_dict['name']}")
    try:
        repo.label(label_dict["name"])
    except github3.exceptions.NotFoundError:
        repo.create_label(**label_dict)


def label_pr(
    repo: github3.repos.Repository,
    pr_json: LazyJson,
    label_dict: dict,
    dry_run: bool = False,
) -> None:
    ensure_label_exists(repo, label_dict, dry_run)
    if dry_run:
        print(f"dry run: label pr {pr_json['number']} with {label_dict['name']}")
    else:
        iss = repo.issue(pr_json["number"])
        iss.add_labels(label_dict["name"])


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
