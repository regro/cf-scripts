from fastapi import APIRouter

from tests_integration.lib.integration_test_helper import IntegrationTestHelper

router = APIRouter()


@router.get("/pypi.org/pypi/pydantic/json")
def handle():
    return {
        "new_version": "1.8.2",
    }


def prepare(helper: IntegrationTestHelper):
    pass
