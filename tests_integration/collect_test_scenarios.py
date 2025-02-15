import collections
import os
import random

from tests_integration.lib.shared import DEFINITIONS_DIR, ENV_GITHUB_RUN_ID

SKIP_TEST_CASES = {"__init__"}


def collect_integration_test_cases() -> dict[str, list[str]]:
    """
    For each feedstock, return a list of all test cases that should be run for it.
    The test cases do not include the feedstock name or the .py extension.

    Example return value:
    {
        "feedstock1": ["aarch_migration", "version_update"],
        "feedstock2": ["version_update"],
    }

    The return value of this function is sorted by feedstock name and test case name.
    """
    test_cases = collections.defaultdict(list)

    for test_case in DEFINITIONS_DIR.glob("*/*.py"):
        test_case_name = test_case.stem
        if test_case_name in SKIP_TEST_CASES:
            continue
        feedstock = test_case.parent.name
        test_cases[feedstock].append(test_case_name)

    return dict(
        sorted(
            (feedstock, sorted(test_cases))
            for feedstock, test_cases in test_cases.items()
        )
    )


def get_number_of_test_scenarios(integration_test_cases: dict[str, list[str]]) -> int:
    return max(len(test_cases) for test_cases in integration_test_cases.values())


def get_all_test_scenario_ids(
    integration_test_cases: dict[str, list[str]],
) -> list[int]:
    return list(range(get_number_of_test_scenarios(integration_test_cases)))


def init_random():
    random.seed(int(os.environ[ENV_GITHUB_RUN_ID]))


def get_test_scenario(scenario_id: int) -> dict[str, str]:
    """
    Get the test scenario for the given ID.
    The scenario is a dictionary with the feedstock name as key and the test case name as value.

    Test scenarios are pseudo-randomly generated with the GitHub run ID as seed.
    """
    init_random()
    integration_test_cases = collect_integration_test_cases()

    n_scenarios = get_number_of_test_scenarios(integration_test_cases)

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
        for feedstock, test_cases in integration_test_cases.items()
    }

    for test_cases in test_cases_extended.values():
        # in-place
        random.shuffle(test_cases)

    def pop_test_scenario():
        scenario: dict[str, str] = {}
        for feedstock in test_cases_extended:
            scenario[feedstock] = test_cases_extended[feedstock].pop()
        return scenario

    for _ in range(scenario_id):
        pop_test_scenario()

    return pop_test_scenario()
