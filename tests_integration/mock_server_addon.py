"""
Start this file with `mitmdump -s mock_server_addon.py`.

This file expects an environment variable to be set to the ID of the test scenario to run.
The name of this variable is defined in `ENV_TEST_SCENARIO_ID`.

Starting mitmdump from a Python script is not officially supported.
"""

import fnmatch
import logging
import os

from fastapi import FastAPI
from mitmproxy.addons import asgiapp
from mitmproxy.http import HTTPFlow

from tests_integration.collect_test_scenarios import get_test_scenario
from tests_integration.lib.shared import (
    ENV_TEST_SCENARIO_ID,
    TRANSPARENT_URLS,
    VIRTUAL_PROXY_HOSTNAME,
    VIRTUAL_PROXY_PORT,
    get_global_router,
    get_test_case_modules,
)

LOGGER = logging.getLogger(__name__)


def request(flow: HTTPFlow):
    if any(fnmatch.fnmatch(flow.request.url, pattern) for pattern in TRANSPARENT_URLS):
        return
    flow.request.path = f"/{flow.request.host}{flow.request.path}"
    flow.request.host = VIRTUAL_PROXY_HOSTNAME
    flow.request.port = VIRTUAL_PROXY_PORT
    flow.request.scheme = "http"


def _setup_fastapi():
    scenario_id = int(os.environ[ENV_TEST_SCENARIO_ID])
    scenario = get_test_scenario(scenario_id)

    app = FastAPI()

    app.include_router(get_global_router())

    for test_module in get_test_case_modules(scenario):
        LOGGER.info("Setting up mocks for %s...", test_module.__name__)
        try:
            app.include_router(test_module.router)
        except AttributeError:
            raise AttributeError("The test case must define a FastAPI router.")

    return app


addons = [
    asgiapp.ASGIApp(_setup_fastapi(), VIRTUAL_PROXY_HOSTNAME, VIRTUAL_PROXY_PORT),
]
