from pathlib import Path

from fastapi import APIRouter

from ..base_classes import AbstractIntegrationTestHelper, TestCase


class VersionUpdate(TestCase):
    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/pypi.org/pypi/fastapi/json")
        def handle_pypi_json_api():
            return {
                # rest omitted
                "info": {"name": "fastapi", "version": "0.116.1"}
            }

        return router

    def prepare(self, helper: AbstractIntegrationTestHelper):
        feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
        helper.overwrite_feedstock_contents("fastapi", feedstock_dir)

    def validate(self, helper: AbstractIntegrationTestHelper):
        helper.assert_version_pr_present_v1(
            "fastapi",
            new_version="0.116.1",
            new_hash="ed52cbf946abfd70c5a0dccb24673f0670deeb517a88b3544d03c2a6bf283143",
            old_version="0.116.0",
            old_hash="80dc0794627af0390353a6d1171618276616310d37d24faba6648398e57d687a",
        )


ALL_TEST_CASES: list[TestCase] = [VersionUpdate()]
