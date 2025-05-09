"""
This file contains classes that both _definitions and lib are referring to.
To avoid circular imports, it needs to be separate.
"""

from abc import ABC
from enum import StrEnum
from pathlib import Path

from fastapi import APIRouter


class GitHubAccount(StrEnum):
    CONDA_FORGE_ORG = "conda-forge-bot-staging"
    BOT_USER = "regro-cf-autotick-bot-staging"
    REGRO_ORG = "regro-staging"


class AbstractIntegrationTestHelper(ABC):
    """
    This is an abstract base class for the IntegrationTestHelper in tests_integration.lib.
    Without this class, we cannot refer to IntegrationTestHelper in the definitions module
    because it would create a circular import. So we refer to this class instead
    and make sure that IntegrationTestHelper inherits from this class.
    """

    def overwrite_feedstock_contents(
        self, feedstock_name: str, source_dir: Path, branch: str = "main"
    ):
        """
        Overwrite the contents of the feedstock with the contents of the source directory.
        This prunes the entire git history.

        :param feedstock_name: The name of the feedstock repository, without the "-feedstock" suffix.
        :param source_dir: The directory containing the new contents of the feedstock.
        :param branch: The branch to overwrite.
        """
        pass

    def overwrite_github_repository(
        self,
        owner_account: GitHubAccount,
        repo_name: str,
        source_dir: Path,
        branch: str = "main",
    ):
        """
        Overwrite the contents of the repository with the contents of the source directory.
        This prunes the entire git history.

        :param owner_account: The owner of the repository.
        :param repo_name: The name of the repository.
        :param source_dir: The directory containing the new contents of the repository.
        :param branch: The branch to overwrite.
        """
        pass

    def assert_version_pr_present(
        self,
        feedstock: str,
        new_version: str,
        new_hash: str,
        old_version: str,
        old_hash: str,
    ):
        """
        Asserts that the bot has opened a version update PR.

        :param feedstock: The feedstock we expect the PR for, without the -feedstock suffix.
        :param new_version: The new version that is expected.
        :param new_hash: The new SHA-256 source artifact hash.
        :param old_version: The old version of the feedstock, to check that it no longer appears in the recipe.
        :param old_hash: The old SHA-256 source artifact hash, to check that it no longer appears in the recipe.

        :raises AssertionError: if the assertion fails
        """
        pass


class TestCase(ABC):
    """
    Abstract base class for a single test case in a scenario.
    Per test case, there is exactly one instance of this class statically created
    in the definition of the ALL_TEST_CASES list of the feedstock module.
    Note that a test case (i.e. an instance of this class) might be run multiple times,
    so be careful with state you keep in the instance.
    """

    def get_router(self) -> APIRouter:
        """
        Return the FastAPI router for the test case.
        """
        pass

    def prepare(self, helper: AbstractIntegrationTestHelper):
        """
        Prepare the test case using the given helper.
        """
        pass

    def validate(self, helper: AbstractIntegrationTestHelper):
        """
        Validate the test case using the given helper.
        """
        pass
