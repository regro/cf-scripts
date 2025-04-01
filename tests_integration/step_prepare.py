"""
After closing all open Pull Requests in the conda-forge staging organization,
runs the prepare() function of all test cases of the current test scenario to prepare the test environment.

Expects the scenario ID to be present in the environment variable named SCENARIO_ID.
"""

import logging
from pathlib import Path

from github import Github

from conda_forge_tick.settings import settings
from tests_integration.lib.integration_test_helper import IntegrationTestHelper
from tests_integration.lib.shared import (
    FEEDSTOCK_SUFFIX,
    GitHubAccount,
    get_github_token,
)
from tests_integration.lib.test_case import TestCase

LOGGER = logging.getLogger(__name__)


def close_all_open_pull_requests():
    github = Github(get_github_token(GitHubAccount.CONDA_FORGE_ORG))
    org = github.get_organization(GitHubAccount.CONDA_FORGE_ORG)

    for repo in org.get_repos():
        if not repo.name.endswith(FEEDSTOCK_SUFFIX):
            continue
        for pr in repo.get_pulls(state="open"):
            pr.create_issue_comment(
                "Closing this PR because it is a leftover from a previous test run."
            )
            pr.edit(state="closed")


def reset_cf_graph():
    IntegrationTestHelper.overwrite_github_repository(
        GitHubAccount.REGRO_ORG,
        "cf-graph-countyfair",
        Path(__file__).parent / "resources" / "empty-graph",
        branch=settings().graph_repo_default_branch,
    )


def run_all_prepare_functions(scenario: dict[str, TestCase]):
    test_helper = IntegrationTestHelper()
    for feedstock_name, test_case in scenario.items():
        LOGGER.info("Preparing %s...", feedstock_name)
        test_case.prepare(test_helper)
