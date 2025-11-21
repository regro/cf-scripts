from pathlib import Path

from fastapi import APIRouter

from ..base_classes import AbstractIntegrationTestHelper, TestCase


class VersionUpdate(TestCase):
    def get_router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/pypi.org/pypi/polars/json")
        def handle_pypi_json_api_polars():
            return {
                # rest omitted
                "info": {"name": "fastapi", "version": "1.35.2"}
            }

        @router.get("/pypi.org/pypi/polars-runtime-32/json")
        def handle_pypi_json_api_polars_runtime_32():
            return {
                # rest omitted
                "info": {"name": "fastapi", "version": "1.35.2"}
            }

        @router.get("/pypi.org/pypi/polars-runtime-64/json")
        def handle_pypi_json_api_polars_runtime_64():
            return {
                # rest omitted
                "info": {"name": "fastapi", "version": "1.35.2"}
            }

        @router.get("/pypi.org/pypi/polars-runtime-compat/json")
        def handle_pypi_json_api_polars_runtime_compat():
            return {
                # rest omitted
                "info": {"name": "fastapi", "version": "1.35.2"}
            }

        return router

    def prepare(self, helper: AbstractIntegrationTestHelper):
        feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
        helper.overwrite_feedstock_contents("polars", feedstock_dir)

    def validate(self, helper: AbstractIntegrationTestHelper):
        # https://github.com/conda-forge/polars-feedstock/pull/350

        # polars
        helper.assert_bot_pr_contents_v1(
            feedstock="polars",
            title_contains="v1.35.2",
            included=[
                "1.35.2",
                "ae458b05ca6e7ca2c089342c70793f92f1103c502dc1b14b56f0a04f2cc1d205",
                "6e6e35733ec52abe54b7d30d245e6586b027d433315d20edfb4a5d162c79fe90",
                "8ebdc7b71e72321276419f0f5fdb10ec7a969b40172961c6a49ca50f59b3a601",
                "1947c6ecfe0b42bb85ff1519eb2d62abb2247d52b8ce52156fff0595b4a82d8a",
            ],
            not_included=[
                "1.35.1",
                "06548e6d554580151d6ca7452d74bceeec4640b5b9261836889b8e68cfd7a62e",
                "f6b4ec9cd58b31c87af1b8c110c9c986d82345f1d50d7f7595b5d447a19dc365",
                "50fa6adff602e8c6e5e376f1d2586032e9b087ed0f4a186a0b2dc1b063f5b58b",
                "a66b5365be0f46b83382c65529c5088ef3762859ac2f3410beb1de6084e249f5",
            ],
        )


ALL_TEST_CASES: list[TestCase] = [VersionUpdate()]
