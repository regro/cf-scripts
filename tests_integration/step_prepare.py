"""
After closing all open Pull Requests in the conda-forge staging organization,
runs the prepare() method of all test cases of the current test scenario to prepare the test environment.
"""

import importlib
import logging
import sys

from github import Github

from tests_integration.collect_test_scenarios import get_test_scenario
from tests_integration.shared import (
    FEEDSTOCK_SUFFIX,
    GitHubAccount,
    get_github_token,
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


def run_all_prepare_functions(scenario: dict[str, str]):
    for feedstock, test_case in scenario.items():
        test_case_module = importlib.import_module(
            f"tests_integration.definitions.{feedstock}.{test_case}"
        )

        try:
            test_case_module.prepare()
        except AttributeError:
            raise AttributeError("The test case must define a prepare() function.")


def main(scenario_id: int):
    close_all_open_pull_requests()
    scenario = get_test_scenario(scenario_id)

    logging.info("Preparing test scenario %d...", scenario_id)
    logging.info("Scenario: %s", scenario)

    run_all_prepare_functions(scenario)


if __name__ == "__main__":
    setup_logging(logging.INFO)
    if len(sys.argv) != 2:
        raise ValueError("Expected exactly one argument: the scenario ID.")
    main(int(sys.argv[1]))
