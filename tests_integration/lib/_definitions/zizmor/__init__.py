from pathlib import Path

from fastapi import APIRouter
from starlette.responses import RedirectResponse

from ..base_classes import AbstractIntegrationTestHelper, TestCase


class VersionUpdate(TestCase):
    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/github.com/zizmorcore/zizmor/releases/latest")
        def handle_github_latest_release():
            return RedirectResponse(
                url="https://github.com/zizmorcore/zizmor/releases/tags/v1.18.0"
            )

        @router.get("/github.com/zizmorcore/zizmor/releases/tags/v1.18.0")
        def handle_github_release():
            return "Release v1.18.0"

        return router

    def prepare(self, helper: AbstractIntegrationTestHelper):
        feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
        helper.overwrite_feedstock_contents("zizmor", feedstock_dir)

    def validate(self, helper: AbstractIntegrationTestHelper):
        helper.assert_version_pr_present_v1(
            "zizmor",
            new_version="1.18.0",
            new_hash="17633af9cdf5ca6b5fd31468dfc3dce262b6ff85b244dfc397c484969bfba634",
            old_version="1.16.3",
            old_hash="0953b0bd6016b929a743b18e693b9cf8e0f2766e53531a64134f6d762965e933",
        )


ALL_TEST_CASES: list[TestCase] = [VersionUpdate()]
