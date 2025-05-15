from pathlib import Path

from fastapi import APIRouter

from ..base_classes import AbstractIntegrationTestHelper, TestCase


class SetupPinnings(TestCase):
    def get_router(self) -> APIRouter:
        return APIRouter()

    def prepare(self, helper: AbstractIntegrationTestHelper):
        feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
        helper.overwrite_feedstock_contents("conda-forge-pinning", feedstock_dir)

    def validate(self, helper: AbstractIntegrationTestHelper):
        pass


ALL_TEST_CASES: list[TestCase] = [SetupPinnings()]
