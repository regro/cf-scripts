from pathlib import Path

from fastapi import APIRouter

from tests_integration.lib.integration_test_helper import IntegrationTestHelper

router = APIRouter()


@router.get("/pypi.org/pypi/pydantic/json")
def handle():
    return {
        # rest omitted
        "info": {"name": "pydantic", "version": "2.10.2"}
    }


def prepare(helper: IntegrationTestHelper):
    feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
    helper.overwrite_feedstock_contents("pydantic", feedstock_dir)


def validate(helper: IntegrationTestHelper):
    helper.assert_version_pr_present(
        "pydantic",
        new_version="2.10.2",
        new_hash="2bc2d7f17232e0841cbba4641e65ba1eb6fafb3a08de3a091ff3ce14a197c4fa",
        old_version="2.10.1",
        old_hash="a4daca2dc0aa429555e0656d6bf94873a7dc5f54ee42b1f5873d666fb3f35560",
    )
