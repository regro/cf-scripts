from pathlib import Path

import pytest
from flaky import flaky
from test_migrators import run_test_migration

from conda_forge_tick.migrators import (
    CombineV1ConditionsMigrator,
    Version,
)
from conda_forge_tick.migrators.recipe_v1 import (
    get_condition,
    is_negated_condition,
)

YAML_PATH = Path(__file__).parent / "test_v1_yaml"

combine_conditions_migrator = Version(
    set(),
    piggy_back_migrations=[CombineV1ConditionsMigrator()],
)


@pytest.mark.parametrize(
    "a,b",
    [
        ("unix", "not unix"),
        ('cuda_compiler_version == "None"', 'not cuda_compiler_version == "None"'),
        ('cuda_compiler_version == "None"', 'cuda_compiler_version != "None"'),
        ('not cuda_compiler_version == "None"', 'not cuda_compiler_version != "None"'),
        (
            'cuda_compiler_version != "None" and linux',
            'not (cuda_compiler_version != "None" and linux)',
        ),
        ("linux or osx", "not (linux or osx)"),
        ("a >= 14", "a < 14"),
        ("a >= 14", "not (a >= 14)"),
        ("a in [1, 2, 3]", "a not in [1, 2, 3]"),
        ("a in [1, 2, 3]", "not a in [1, 2, 3]"),
        ("a + b < 10", "a + b >= 10"),
        ("a == b == c", "not (a == b == c)"),
    ],
)
def test_is_negated_condition(a, b):
    a_cond = get_condition({"if": a})
    b_cond = get_condition({"if": b})
    assert is_negated_condition(a_cond, b_cond)
    assert is_negated_condition(b_cond, a_cond)


@pytest.mark.parametrize(
    "a,b",
    [
        ("not unix", "not unix"),
        ('cuda_compiler_version == "None"', 'not cuda_compiler_version != "None"'),
        ('cuda_compiler_version != "None"', 'not cuda_compiler_version == "None"'),
        ("a or b", "not a or b"),
        ("a and b", "not a and b"),
        ("a == b == c", "a != b != c"),
        ("a > 4", "a < 4"),
        ("a == b == c", "not (a == b) == c"),
    ],
)
def test_not_is_negated_condition(a, b):
    a_cond = get_condition({"if": a})
    b_cond = get_condition({"if": b})
    assert not is_negated_condition(a_cond, b_cond)
    assert not is_negated_condition(b_cond, a_cond)


@flaky
def test_combine_v1_conditions(tmp_path):
    run_test_migration(
        m=combine_conditions_migrator,
        inp=YAML_PATH.joinpath("version_pytorch.yaml").read_text(),
        output=YAML_PATH.joinpath("version_pytorch_correct.yaml").read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "2.6.0"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "2.6.0",
        },
        tmp_path=tmp_path,
        recipe_version=1,
    )
