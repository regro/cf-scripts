from tests_integration.definitions import conda_forge_pinning, pydantic
from tests_integration.lib.test_case import TestCase

TEST_CASE_MAPPING: dict[str, list[TestCase]] = {
    "conda-forge-pinning": conda_forge_pinning.ALL_TEST_CASES,
    "pydantic": pydantic.ALL_TEST_CASES,
}
"""
Maps from feedstock name to a list of all test cases for that feedstock.
"""
