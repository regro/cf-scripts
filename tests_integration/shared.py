import importlib
import logging
import os
import types
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path

from fastapi import APIRouter


class GitHubAccount(StrEnum):
    CONDA_FORGE_ORG = "conda-forge-bot-staging"
    BOT_USER = "regro-cf-autotick-bot-staging"
    REGRO_ORG = "regro-staging"


GITHUB_TOKEN_ENV_VARS: dict[GitHubAccount, str] = {
    GitHubAccount.CONDA_FORGE_ORG: "GH_TOKEN_STAGING_CONDA_FORGE",
    GitHubAccount.BOT_USER: "GH_TOKEN_STAGING_BOT_USER",
    GitHubAccount.REGRO_ORG: "GH_TOKEN_STAGING_REGRO",
}

IS_USER_ACCOUNT: dict[GitHubAccount, bool] = {
    GitHubAccount.CONDA_FORGE_ORG: False,
    GitHubAccount.BOT_USER: True,
    GitHubAccount.REGRO_ORG: False,
}

REGRO_ACCOUNT_REPOS = {
    "cf-graph-countyfair",
}

ENV_GITHUB_OUTPUT = "GITHUB_OUTPUT"
ENV_GITHUB_RUN_ID = "GITHUB_RUN_ID"
"""
Used as a random seed for the integration tests.
"""
ENV_TEST_SCENARIO_ID = "SCENARIO_ID"

GITHUB_OUTPUT_KEY_SCENARIO_IDS = "scenario_ids"

TESTS_INTEGRATION_DIR_NAME = "tests_integration"
DEFINITIONS_DIR_NAME = "definitions"

DEFINITIONS_DIR = Path(__file__).parent / DEFINITIONS_DIR_NAME

FEEDSTOCK_SUFFIX = "-feedstock"


def setup_logging(level: int | str):
    logging.basicConfig(level=level)


def get_github_token(account: GitHubAccount) -> str:
    return os.environ[GITHUB_TOKEN_ENV_VARS[account]]


def is_user_account(account: GitHubAccount) -> bool:
    return IS_USER_ACCOUNT[account]


def write_github_output(key: str, value: str):
    with open(os.environ[ENV_GITHUB_OUTPUT], "a") as f:
        f.write(f"{key}={value}\n")


def get_test_case_modules(scenario: dict[str, str]) -> Iterator[types.ModuleType]:
    """
    Yields all test case modules of the given scenario.
    """
    return (
        importlib.import_module(
            f"{TESTS_INTEGRATION_DIR_NAME}.{DEFINITIONS_DIR_NAME}.{feedstock}.{test_case}"
        )
        for feedstock, test_case in scenario.items()
    )


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
