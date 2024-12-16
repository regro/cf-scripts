import importlib
import logging
import os
import ssl
import types
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path

import httpx
import truststore
from fastapi import APIRouter, Request, Response


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

DEFINITIONS_DIR = Path(__file__).parent / DEFINITIONS_DIR_NAME

FEEDSTOCK_SUFFIX = "-feedstock"

TRANSPARENT_URLS = {
    "https://raw.githubusercontent.com/regro/cf-graph-countyfair/master/mappings/pypi/name_mapping.yaml",
    "https://raw.githubusercontent.com/regro/cf-graph-countyfair/master/mappings/pypi/grayskull_pypi_mapping.json",
    "https://api.github.com/*",  # anything that starts with https://api.github.com/
    "https://pypi.io/packages/source/*",  # source archives from PyPI
    "https://api.anaconda.org/package/conda-forge/conda-forge-pinning",
    "https://api.anaconda.org/download/conda-forge/conda-forge-pinning/*",
}
"""
Those URLs are redirected to the actual upstream URLs in the tests.
"""

ALL_HTTP_METHODS = [
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "DELETE",
    "CONNECT",
    "OPTIONS",
    "TRACE",
    "PATCH",
]


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


def _get_proxy_request_handler():
    async def handle_redirect(request: Request):
        # use system CA certificates for better debugging support
        ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        async with httpx.AsyncClient(verify=ssl_context) as client:
            forward_hostname = request.url.path.split("/")[1]
            target_url = request.url.replace(
                scheme="https",
                port=443,
                hostname=forward_hostname,
                path="/".join(request.url.path.split("/")[2:]),
            )
            forward_headers = dict(request.headers)
            forward_headers["host"] = forward_hostname
            print(request.method + " " + str(target_url))
            proxy = await client.request(
                method=request.method,
                url=str(target_url),
                headers=forward_headers,
            )
        return Response(
            content=proxy.content,
            status_code=proxy.status_code,
            headers=dict(proxy.headers),
        )

    return handle_redirect


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

    # for url in TRANSPARENT_URLS:
    #    assert url.startswith("https://")

    # router.add_route(
    #    url.replace("https://", "/"),
    #    _get_proxy_request_handler(),
    #    methods=ALL_HTTP_METHODS,
    # )

    return router


VIRTUAL_PROXY_HOSTNAME = "virtual.proxy"
VIRTUAL_PROXY_PORT = 80
