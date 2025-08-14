"""
Module providing base classes for the integration tests.

Both _definitions and lib refer to this module.
"""

import os
from abc import ABC
from enum import StrEnum
from pathlib import Path

from fastapi import APIRouter


class GitHubAccount(StrEnum):
    CONDA_FORGE_ORG = (
        os.environ.get("GITHUB_ACCOUNT_CONDA_FORGE_ORG") or "conda-forge-bot-staging"
    )
    BOT_USER = (
        os.environ.get("GITHUB_ACCOUNT_BOT_USER") or "regro-cf-autotick-bot-staging"
    )
    REGRO_ORG = os.environ.get("GITHUB_ACCOUNT_REGRO_ORG") or "regro-staging"


class AbstractIntegrationTestHelper(ABC):
    """Abstract base class for the IntegrationTestHelper in tests_integration.lib.
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

        Parameters
        ----------
        feedstock_name
            The name of the feedstock repository, without the "-feedstock" suffix.
        source_dir
            The directory containing the new contents of the feedstock.
        branch
            The branch to overwrite.
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

        Parameters
        ----------
        owner_account
            The owner of the repository.
        repo_name
            The name of the repository.
        source_dir
            The directory containing the new contents of the repository.
        branch
            The branch to overwrite.
        """
        pass

    def assert_version_pr_present_v0(
        self,
        feedstock: str,
        new_version: str,
        new_hash: str,
        old_version: str,
        old_hash: str,
    ) -> None:
        """
        Assert that the bot has opened a version update PR for a v0 recipe.

        Parameters
        ----------
        feedstock
            The feedstock we expect the PR for, without the -feedstock suffix.
        new_version
            The new version that is expected.
        new_hash
            The new SHA-256 source artifact hash.
        old_version
            The old version of the feedstock, to check that it no longer appears in the recipe.
        old_hash
            The old SHA-256 source artifact hash, to check that it no longer appears in the recipe.


        Raises
        ------
        AssertionError
            If the assertion fails.
        """
        pass

    def assert_version_pr_present_v1(
        self,
        feedstock: str,
        new_version: str,
        new_hash: str,
        old_version: str,
        old_hash: str,
    ):
        """
        Assert that the bot has opened a version update PR for a v1 recipe.

        Parameters
        ----------
        feedstock
            The feedstock we expect the PR for, without the -feedstock suffix.
        new_version
            The new version that is expected.
        new_hash
            The new SHA-256 source artifact hash.
        old_version
            The old version of the feedstock, to check that it no longer appears in the recipe.
        old_hash
            The old SHA-256 source artifact hash, to check that it no longer appears in the recipe.


        Raises
        ------
        AssertionError
            If the assertion fails.
        """
        pass

    def assert_new_run_requirements_equal_v1(
        self,
        feedstock: str,
        new_version: str,
        run_requirements: list[str],
    ):
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
        """Return the FastAPI router for the test case."""
        pass

    def prepare(self, helper: AbstractIntegrationTestHelper):
        """Prepare the test case using the given helper."""
        pass

    def validate(self, helper: AbstractIntegrationTestHelper):
        """Validate the test case using the given helper."""
        pass
