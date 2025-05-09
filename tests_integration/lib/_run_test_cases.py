import logging
from importlib import resources

from github import Github

from conda_forge_tick.settings import settings

from ._definitions import GitHubAccount, TestCase
from ._integration_test_helper import IntegrationTestHelper
from ._shared import FEEDSTOCK_SUFFIX, get_github_token

LOGGER = logging.getLogger(__name__)
EMPTY_GRAPH_DIR = resources.files("tests_integration.resources").joinpath("empty-graph")


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
    with resources.as_file(EMPTY_GRAPH_DIR) as empty_graph_dir:
        IntegrationTestHelper().overwrite_github_repository(
            GitHubAccount.REGRO_ORG,
            "cf-graph-countyfair",
            empty_graph_dir,
            branch=settings().graph_repo_default_branch,
        )


def run_all_prepare_functions(scenario: dict[str, TestCase]):
    test_helper = IntegrationTestHelper()
    for feedstock_name, test_case in scenario.items():
        LOGGER.info("Preparing %s...", feedstock_name)
        test_case.prepare(test_helper)


def run_all_validate_functions(scenario: dict[str, TestCase]):
    test_helper = IntegrationTestHelper()
    for feedstock_name, test_case in scenario.items():
        LOGGER.info("Validating %s...", feedstock_name)
        test_case.validate(test_helper)
