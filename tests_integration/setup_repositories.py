"""
This module is used by the integration tests to set up the GitHub repositories
that are needed for running the tests.

We do not *create* any repositories within the bot's user account here. This is handled in the prepare function of the
test cases themselves because tests could purposefully rely on the actual bot itself to create repositories.

However, we do delete unnecessary feedstocks from the bot's user account.

After the repositories are set up, we write a list of all test scenario ids to be run to $GITHUB_OUTPUT.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from github import Github
from github.Repository import Repository

from tests_integration.definitions import TEST_CASE_MAPPING
from tests_integration.lib.shared import (
    FEEDSTOCK_SUFFIX,
    REGRO_ACCOUNT_REPOS,
    GitHubAccount,
    get_github_token,
    is_user_account,
)

LOGGER = logging.getLogger(__name__)

IGNORE_FEEDSTOCK_NAMES = {
    "__pycache__",
}


@dataclass(frozen=True)
class GitHubAccountSetup:
    """
    Information about the setup of a GitHub account for the integration tests.
    """

    account: GitHubAccount
    """
    The GitHub account for which the setup is done.
    """

    target_names: set[str]
    """
    The names of the repositories that should exist after the preparation (excluding the suffix).
    """

    suffix: str | None = None
    """
    If given, only repositories with the given suffix are considered for deletion and the target names
    are extended with the suffix.
    """

    delete_only: bool = False
    """
    If True, only delete unnecessary repositories and do not create any new ones.
    """


class RepositoryOwner(Protocol):
    def create_repo(self, name: str) -> Repository:
        pass

    def get_repo(self, name: str) -> Repository:
        pass

    def get_repos(self) -> Iterable[Repository]:
        pass


def get_test_feedstock_names() -> set[str]:
    """
    Returns the list of feedstock names that are needed for the integration tests.
    The names do not include the "-feedstock" suffix.
    """
    return set(TEST_CASE_MAPPING.keys())


def _or_empty_set(value: set[str]) -> set[str] | str:
    """
    Logging helper function that returns "{}" if the given set is empty.
    """
    return value or "{}"


def prepare_repositories(
    owner: RepositoryOwner,
    owner_name: str,
    existing_repos: Iterable[Repository],
    target_names: Iterable[str],
    delete_only: bool,
    suffix: str | None = None,
):
    """
    Prepares the repositories of a certain owner for the integration tests.
    Unnecessary repositories are deleted and missing repositories are created.

    :param owner: The owner of the repositories.
    :param owner_name: The name of the owner (for logging).
    :param existing_repos: The existing repositories of the owner.
    :param target_names: The names of the repositories that should exist after the preparation (excluding the suffix).
    :param suffix: If given, only repositories with the given suffix are considered for deletion and the target names
                   are extended with the suffix.
    :param delete_only: If True, only delete unnecessary repositories and do not create any new ones.
    """
    existing_names = {repo.name for repo in existing_repos}
    target_names = set(target_names)

    if suffix:
        existing_names = {name for name in existing_names if name.endswith(suffix)}
        target_names = {name + suffix for name in target_names}

    to_delete = existing_names - target_names
    to_create = target_names - existing_names

    LOGGER.info(
        "Deleting the following repositories for %s: %s",
        owner_name,
        _or_empty_set(to_delete),
    )
    for name in to_delete:
        owner.get_repo(name).delete()

    if delete_only:
        return

    LOGGER.info(
        "Creating the following repositories for %s: %s",
        owner_name,
        _or_empty_set(to_create),
    )
    for name in to_create:
        owner.create_repo(name)


def prepare_accounts(setup_infos: Iterable[GitHubAccountSetup]):
    """
    Prepares the repositories of all GitHub accounts for the integration tests.
    """
    for setup_info in setup_infos:
        # for each account, we need to create a separate GitHub instance because different tokens are needed
        github = Github(get_github_token(setup_info.account))

        owner: RepositoryOwner
        existing_repos: Iterable[Repository]
        if is_user_account(setup_info.account):
            current_user = github.get_user()
            if current_user.login != setup_info.account:
                raise ValueError("The token is not for the expected user")
            owner = current_user
            existing_repos = current_user.get_repos(type="owner")
        else:
            owner = github.get_organization(setup_info.account)
            existing_repos = owner.get_repos()

        prepare_repositories(
            owner=owner,
            owner_name=setup_info.account,
            existing_repos=existing_repos,
            target_names=setup_info.target_names,
            delete_only=setup_info.delete_only,
            suffix=setup_info.suffix,
        )


def prepare_all_accounts():
    test_feedstock_names = get_test_feedstock_names()
    LOGGER.info("Test feedstock names: %s", _or_empty_set(test_feedstock_names))

    setup_infos: list[GitHubAccountSetup] = [
        GitHubAccountSetup(
            GitHubAccount.CONDA_FORGE_ORG,
            target_names=test_feedstock_names,
            suffix=FEEDSTOCK_SUFFIX,
        ),
        GitHubAccountSetup(
            GitHubAccount.BOT_USER,
            target_names=set(),
            suffix=FEEDSTOCK_SUFFIX,
            delete_only=True,  # see the top-level comment for the reason
        ),
        GitHubAccountSetup(
            GitHubAccount.REGRO_ORG,
            REGRO_ACCOUNT_REPOS,
        ),
    ]

    prepare_accounts(setup_infos)
