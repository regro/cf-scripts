import logging
import os
from enum import StrEnum
from pathlib import Path

from fastapi import APIRouter

from conda_forge_tick.settings import settings


class GitHubAccount(StrEnum):
    CONDA_FORGE_ORG = "conda-forge-bot-staging"
    BOT_USER = "regro-cf-autotick-bot-staging"
    REGRO_ORG = "regro-staging"


GITHUB_TOKEN_ENV_VARS: dict[GitHubAccount, str] = {
    GitHubAccount.CONDA_FORGE_ORG: "TEST_SETUP_TOKEN",
    GitHubAccount.BOT_USER: "TEST_SETUP_TOKEN",
    GitHubAccount.REGRO_ORG: "TEST_SETUP_TOKEN",
}

IS_USER_ACCOUNT: dict[GitHubAccount, bool] = {
    GitHubAccount.CONDA_FORGE_ORG: False,
    GitHubAccount.BOT_USER: True,
    GitHubAccount.REGRO_ORG: False,
}

REGRO_ACCOUNT_REPOS = {"cf-graph-countyfair"}

ENV_GITHUB_OUTPUT = "GITHUB_OUTPUT"
ENV_GITHUB_RUN_ID = "GITHUB_RUN_ID"
"""
Used as a random seed for the integration tests.
"""
ENV_TEST_SCENARIO_ID = "SCENARIO_ID"

GITHUB_OUTPUT_KEY_SCENARIO_IDS = "scenario_ids"

TESTS_INTEGRATION_DIR_NAME = "tests_integration"
DEFINITIONS_DIR_NAME = "definitions"

DEFINITIONS_DIR = Path(__file__).parents[1] / DEFINITIONS_DIR_NAME

FEEDSTOCK_SUFFIX = "-feedstock"


def setup_logging(default_level: int):
    """
    Set up the Python logging module.
    Uses the passed log level as the default level.
    If running within GitHub Actions and the workflow runs in debug mode, the log level is never set above DEBUG.
    """
    if settings().github_runner_debug and default_level > logging.DEBUG:
        level = logging.DEBUG
    else:
        level = default_level
    logging.basicConfig(level=level)


def get_github_token(account: GitHubAccount) -> str:
    return os.environ[GITHUB_TOKEN_ENV_VARS[account]]


def is_user_account(account: GitHubAccount) -> bool:
    return IS_USER_ACCOUNT[account]


def get_transparent_urls() -> set[str]:
    """
    Returns URLs which should be forwarded to the actual upstream URLs in the tests.
    Unix filename patterns (provided by fnmatch) are used to specify wildcards:
    https://docs.python.org/3/library/fnmatch.html
    """

    # this is not a constant because the graph_repo_default_branch setting is dynamic
    graph_repo_default_branch = settings().graph_repo_default_branch
    transparent_urls = {
        f"https://raw.githubusercontent.com/regro/cf-graph-countyfair/{graph_repo_default_branch}/mappings/pypi/name_mapping.yaml",
        f"https://raw.githubusercontent.com/regro/cf-graph-countyfair/{graph_repo_default_branch}/mappings/pypi/grayskull_pypi_mapping.json",
        "https://raw.githubusercontent.com/regro/cf-scripts/refs/heads/main/conda_forge_tick/cf_tick_schema.json",
        "https://raw.githubusercontent.com/conda-forge/conda-smithy/refs/heads/main/conda_smithy/data/conda-forge.json",
        "https://api.github.com/*",
        "https://github.com/regro-staging/*",
        "https://github.com/conda-forge-bot-staging/*",
        "https://github.com/regro-cf-autotick-bot-staging/*",
        "https://pypi.io/packages/source/*",
        "https://pypi.org/packages/source/*",
        "https://files.pythonhosted.org/packages/*",
        "https://api.anaconda.org/package/conda-forge/conda-forge-pinning",
        "https://api.anaconda.org/download/conda-forge/conda-forge-pinning/*",
        "https://binstar-cio-packages-prod.s3.amazonaws.com/*",
    }

    if any(not url.startswith("https://") for url in transparent_urls):
        # this is to protect against mistakes and typos, adjust if it ever becomes too strict
        raise ValueError("All URLs in transparent_urls must start with https://")

    # silence the PyCharm warning about using http instead of https
    # noinspection HttpUrlsUsage
    http_urls = {url.replace("https://", "http://", 1) for url in transparent_urls}

    return transparent_urls | http_urls


def get_global_router():
    """
    Returns the global FastAPI router to be included in all test scenarios.
    """
    router = APIRouter()

    @router.get("/cran.r-project.org/src/contrib/")
    def handle_cran_index():
        return ""

    @router.get("/cran.r-project.org/src/contrib/Archive/")
    def handle_cran_index_archive():
        return ""

    return router


VIRTUAL_PROXY_HOSTNAME = "virtual.proxy"
VIRTUAL_PROXY_PORT = 80
