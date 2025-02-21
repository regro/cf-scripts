from pathlib import Path

from fastapi import APIRouter

from tests_integration.lib.integration_test_helper import IntegrationTestHelper
from tests_integration.lib.test_case import TestCase


class SetupPinnings(TestCase):
    def get_router(self) -> APIRouter:
        return APIRouter()

    def prepare(self, helper: IntegrationTestHelper):
        feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
        helper.overwrite_feedstock_contents("conda-forge-pinning", feedstock_dir)

    def validate(self, helper: IntegrationTestHelper):
        pass


ALL_TEST_CASES: list[TestCase] = [SetupPinnings()]
