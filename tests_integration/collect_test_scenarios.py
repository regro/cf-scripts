import os
import random

from tests_integration.definitions import TEST_CASE_MAPPING
from tests_integration.lib.shared import ENV_GITHUB_RUN_ID
from tests_integration.lib.test_case import TestCase


def get_number_of_test_scenarios() -> int:
    return max(len(test_cases) for test_cases in TEST_CASE_MAPPING.values())


def get_all_test_scenario_ids() -> list[int]:
    return list(range(get_number_of_test_scenarios()))


def init_random():
    random.seed(int(os.environ.get(ENV_GITHUB_RUN_ID, 0)))


def get_test_scenario(scenario_id: int) -> dict[str, TestCase]:
    """
    Get the test scenario for the given ID.
    The scenario is a dictionary with the feedstock name as key and the test case name as value.

    Test scenarios are pseudo-randomly generated with the GitHub run ID as seed.
    """
    init_random()

    n_scenarios = get_number_of_test_scenarios()

    if n_scenarios < 0 or scenario_id >= n_scenarios:
        raise ValueError(
            f"Invalid scenario ID: {scenario_id}. Must be between 0 and {n_scenarios - 1}."
        )

    # make sure that each feedstock has exactly n_scenarios test cases
    # We have to cut the additional test cases here to avoid that some test cases are not run.
    test_cases_extended = {
        feedstock: (
            test_cases
            * (n_scenarios // len(test_cases) + (n_scenarios % len(test_cases) > 0))
        )[:n_scenarios]
        for feedstock, test_cases in TEST_CASE_MAPPING.items()
    }

    for test_cases in test_cases_extended.values():
        # in-place
        random.shuffle(test_cases)

    def pop_test_scenario():
        scenario: dict[str, TestCase] = {}
        for feedstock in test_cases_extended:
            scenario[feedstock] = test_cases_extended[feedstock].pop()
        return scenario

    for _ in range(scenario_id):
        pop_test_scenario()

    return pop_test_scenario()
