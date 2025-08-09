from pathlib import Path

from fastapi import APIRouter

from ..base_classes import AbstractIntegrationTestHelper, TestCase


class V1VersionUpdate(TestCase):
    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/pypi.org/pypi/azure-cli-core/json")
        def handle_pypi_json_api():
            return {
                # rest omitted
                "info": {"name": "azure-cli-core", "version": "2.76.0"}
            }

        return router

    def prepare(self, helper: AbstractIntegrationTestHelper):
        feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
        helper.overwrite_feedstock_contents("azure-cli-core", feedstock_dir)

    def validate(self, helper: AbstractIntegrationTestHelper):
        helper.assert_version_pr_present_v1(
            "azure-cli-core",
            new_version="2.76.0",
            new_hash="97dbcc4557589cb68356d9f5c3793ecf5d86118622dc78835057e029c7698a95",
            old_version="2.75.0",
            old_hash="0187f93949c806f8e39617cdb3b4fd4e3cac5ebe45f02dc0763850bcf7de8df2",
        )


ALL_TEST_CASES: list[TestCase] = [V1VersionUpdate()]
