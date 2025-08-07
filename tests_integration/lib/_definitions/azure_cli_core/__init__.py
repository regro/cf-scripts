import json
from pathlib import Path

from fastapi import APIRouter

from ..base_classes import AbstractIntegrationTestHelper, TestCase


class GrayskullV1VersionUpdate(TestCase):
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
        helper.assert_runtime_requirements_equals(
            "azure-cli-core",
            new_version="2.76.0",
            runtime_requirements=[
                "python >=${{ python_min }}",
                "argcomplete >=3.5.2,<3.6.dev0",
                "azure-cli-telemetry ==1.1.0.*",
                "azure-mgmt-core >=1.2.0,<2",
                "cryptography",
                "distro",
                "humanfriendly >=10.0,<11.dev0",
                "jmespath",
                "knack >=0.11.0,<0.12.dev0",
                "microsoft-security-utilities-secret-masker >=1.0.0b4,<1.1.dev0",
                "msal ==1.33.0b1",
                "msal_extensions ==1.2.0",
                "packaging >=20.9",
                "pkginfo >=1.5.0.1",
                "psutil >=5.9",
                "py-deviceid",
                "pyjwt >=2.1.0",
                "pyopenssl >=17.1.0",
                "requests",
            ]
        )


ALL_TEST_CASES: list[TestCase] = [GrayskullV1VersionUpdate()]
