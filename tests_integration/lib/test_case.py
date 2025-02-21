from abc import ABC

from fastapi import APIRouter

from tests_integration.lib.integration_test_helper import IntegrationTestHelper


class TestCase(ABC):
    """
    Abstract base class for a single test case in a scenario.
    """

    def get_router(self) -> APIRouter:
        """
        Return the FastAPI router for the test case.
        """
        pass

    def prepare(self, helper: IntegrationTestHelper):
        """
        Prepare the test case using the given helper.
        """
        pass

    def validate(self, helper: IntegrationTestHelper):
        """
        Validate the test case using the given helper.
        """
        pass
