from abc import ABC

from fastapi import APIRouter

from ._integration_test_helper import IntegrationTestHelper


class TestCase(ABC):
    """
    Abstract base class for a single test case in a scenario.
    Per test case, there is exactly one instance of this class statically created
    in the definition of the ALL_TEST_CASES list of the feedstock module.
    Note that a test case (i.e. an instance of this class) might be run multiple times,
    so be careful with state you keep in the instance.
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
