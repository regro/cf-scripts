"""
Runs the validate() functions of all test cases of the current test scenario to make test assertions.

Expects the scenario ID to be present in the environment variable SCENARIO_ID.
"""

import logging

from tests_integration.lib.integration_test_helper import IntegrationTestHelper
from tests_integration.lib.test_case import TestCase

LOGGER = logging.getLogger(__name__)


def run_all_validate_functions(scenario: dict[str, TestCase]):
    test_helper = IntegrationTestHelper()
    for feedstock_name, test_case in scenario.items():
        LOGGER.info("Validating %s...", feedstock_name)
        test_case.validate(test_helper)
