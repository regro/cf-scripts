#!/usr/bin/env mitmdump -s
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

from tests_integration.lib import (
    ENV_TEST_SCENARIO_ID,
    VIRTUAL_PROXY_HOSTNAME,
    VIRTUAL_PROXY_PORT,
    get_global_router,
    get_test_scenario,
    get_transparent_urls,
)

LOGGER = logging.getLogger(__name__)


def request(flow: HTTPFlow):
    if any(
        fnmatch.fnmatch(flow.request.url, pattern) for pattern in get_transparent_urls()
    ):
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

    for feedstock_name, test_case in scenario.items():
        LOGGER.info("Setting up mocks for %s...", feedstock_name)
        app.include_router(test_case.get_router())

    return app


addons = [
    asgiapp.ASGIApp(_setup_fastapi(), VIRTUAL_PROXY_HOSTNAME, VIRTUAL_PROXY_PORT),
]
