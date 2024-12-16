from pathlib import Path

from fastapi import APIRouter

from tests_integration.lib.integration_test_helper import IntegrationTestHelper

router = APIRouter()


def prepare(helper: IntegrationTestHelper):
    feedstock_dir = Path(__file__).parent / "resources" / "feedstock"
    helper.overwrite_feedstock_contents("llvmdev", feedstock_dir)


def validate(helper: IntegrationTestHelper):
    pass
