import json
from pathlib import Path

from fastapi import APIRouter

from ..base_classes import AbstractIntegrationTestHelper, TestCase


class VersionUpdate(TestCase):
    """Test case for dominodatalab version update from 1.4.7 to 2.0.0.

    This test case is designed to reproduce the issue where the bot fails
    to update dominodatalab with the error:
    "Failed to render recipe YAML! No output recipes found!"
    """

    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/pypi.org/pypi/dominodatalab/json")
        def handle_pypi_json_api():
            # Must include 'urls' with sdist info for grayskull to find the package
            return {
                "info": {"name": "dominodatalab", "version": "2.0.0"},
                "urls": [
                    {
                        "packagetype": "sdist",
                        "url": "https://files.pythonhosted.org/packages/d8/6d/1e321187451c1cc1670e615497474f9c54f04ad5f4ff7e831ea2dc3eeb23/dominodatalab-2.0.0.tar.gz",
                    }
                ],
            }

        @router.get("/pypi.org/pypi/dominodatalab/2.0.0/json")
        def handle_pypi_version_json_api():
            return json.loads(
                Path(__file__)
                .parent.joinpath("pypi_version_json_response.json")
                .read_text()
            )

        return router

    def prepare(self, helper: AbstractIntegrationTestHelper):
        feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
        helper.overwrite_feedstock_contents("dominodatalab", feedstock_dir)

    def validate(self, helper: AbstractIntegrationTestHelper):
        helper.assert_version_pr_present_v1(
            "dominodatalab",
            new_version="2.0.0",
            new_hash="05d0f44a89bf0562413018f638839e31bdc108d6ed67869d5ccaceacf41ee237",
            old_version="1.4.7",
            old_hash="d016b285eba676147b2e4b0c7cc235b71b5a2009e7421281f7246a6ec619342c",
        )
        # Assert that the dep_updates migrator didn't fail silently
        # If grayskull fails to generate a valid recipe for dependency analysis,
        # the PR body will contain this error message
        helper.assert_pr_body_not_contains(
            "dominodatalab",
            new_version="2.0.0",
            not_included=[
                "We couldn't run dependency analysis due to an internal error in the bot, depfinder, or grayskull."
            ],
        )


ALL_TEST_CASES: list[TestCase] = [VersionUpdate()]
