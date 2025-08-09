from . import azure_cli_core, conda_forge_pinning, pydantic
from .base_classes import AbstractIntegrationTestHelper, GitHubAccount, TestCase

TEST_CASE_MAPPING: dict[str, list[TestCase]] = {
    "azure-cli-core": azure_cli_core.ALL_TEST_CASES,
    "conda-forge-pinning": conda_forge_pinning.ALL_TEST_CASES,
    "pydantic": pydantic.ALL_TEST_CASES,
}
"""
Maps from feedstock name to a list of all test cases for that feedstock.
"""

__all__ = [
    "AbstractIntegrationTestHelper",
    "GitHubAccount",
    "TestCase",
    "TEST_CASE_MAPPING",
]
