"""
After closing all open Pull Requests in the conda-forge staging organization,
runs the prepare() function of all test cases of the current test scenario to prepare the test environment.

Expects the scenario ID to be present in the environment variable named SCENARIO_ID.
"""

import logging
import os
from pathlib import Path

from github import Github

from conda_forge_tick.settings import GRAPH_REPO_DEFAULT_BRANCH
from tests_integration.collect_test_scenarios import get_test_scenario
from tests_integration.lib.integration_test_helper import IntegrationTestHelper
from tests_integration.lib.shared import (
    ENV_TEST_SCENARIO_ID,
    FEEDSTOCK_SUFFIX,
    GitHubAccount,
    get_github_token,
    get_test_case_modules,
    setup_logging,
)

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
        branch=GRAPH_REPO_DEFAULT_BRANCH,
    )


def run_all_prepare_functions(scenario: dict[str, str]):
    test_helper = IntegrationTestHelper()
    for test_module in get_test_case_modules(scenario):
        LOGGER.info("Preparing %s...", test_module.__name__)
        try:
            prepare_function = test_module.prepare
        except AttributeError as e:
            raise AttributeError(
                "The test case must define a prepare() function."
            ) from e

        prepare_function(test_helper)


def main(scenario_id: int):
    close_all_open_pull_requests()
    reset_cf_graph()

    scenario = get_test_scenario(scenario_id)

    LOGGER.info("Preparing test scenario %d...", scenario_id)
    LOGGER.info("Scenario: %s", scenario)

    run_all_prepare_functions(scenario)


if __name__ == "__main__":
    setup_logging(logging.INFO)
    main(int(os.environ[ENV_TEST_SCENARIO_ID]))
