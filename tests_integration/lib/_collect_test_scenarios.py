import os
import random

from ._definitions import TEST_CASE_MAPPING, TestCase
from ._shared import ENV_GITHUB_RUN_ID


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

    Raises
    ------
    ValueError
        If the scenario ID is invalid (i.e. not between 0 and n_scenarios - 1).
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

    # At this point, test_cases_extended[feedstock][i] is the test case for
    # feedstock "feedstock" in the i-th test scenario.
    # We need to return the i-th test scenario, so we set i to scenario_id.
    return {
        feedstock: test_cases_extended[feedstock][scenario_id]
        for feedstock in test_cases_extended
    }
