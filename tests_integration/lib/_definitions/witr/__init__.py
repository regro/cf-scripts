from pathlib import Path

from fastapi import APIRouter
from starlette.responses import RedirectResponse

from ..base_classes import AbstractIntegrationTestHelper, TestCase


class VersionUpdateAutomerge(TestCase):
    """
    Test case for verifying that version update PRs include the [bot-automerge] prefix
    when the feedstock has automerge enabled in conda-forge.yml.
    """

    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/github.com/pranshuparmar/witr/releases/latest")
        def handle_github_latest_release():
            return RedirectResponse(
                url="https://github.com/pranshuparmar/witr/releases/tags/v0.2.0"
            )

        @router.get("/github.com/pranshuparmar/witr/releases/tags/v0.2.0")
        def handle_github_release():
            return "Release v0.2.0"

        return router

    def prepare(self, helper: AbstractIntegrationTestHelper):
        feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
        helper.overwrite_feedstock_contents("witr", feedstock_dir)

    def validate(self, helper: AbstractIntegrationTestHelper):
        helper.assert_version_pr_present_v1(
            "witr",
            new_version="0.2.0",
            new_hash="9f308ff410033b511cd731de52b877098d8f3b4db83382e482e4f84432497c99",
            old_version="0.1.8",
            old_hash="31ec1c55d9898a27a066de684caa44becbced2fe8c12c0b0e831b2ff9d62f6d0",
        )
        helper.assert_pr_title_starts_with(
            "witr",
            pr_title_contains="v0.2.0",
            expected_prefix="[bot-automerge]",
        )


ALL_TEST_CASES: list[TestCase] = [VersionUpdateAutomerge()]
