from pathlib import Path

from fastapi import APIRouter

from tests_integration.lib.integration_test_helper import IntegrationTestHelper

router = APIRouter()


@router.get("/pypi.org/pypi/pydantic/json")
def handle():
    return {
        # rest omitted
        "info": {"name": "pydantic", "version": "2.10.3"}
    }


def prepare(helper: IntegrationTestHelper):
    feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
    helper.overwrite_feedstock_contents("pydantic", feedstock_dir)
