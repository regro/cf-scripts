from pathlib import Path

import pytest
from flaky import flaky
from test_migrators import run_test_migration

from conda_forge_tick.migrators import (
    CombineV1ConditionsMigrator,
    Version,
)
from conda_forge_tick.migrators.recipe_v1 import (
    is_negated_condition,
    is_single_expression,
)

YAML_PATH = Path(__file__).parent / "test_v1_yaml"

combine_conditions_migrator = Version(
    set(),
    piggy_back_migrations=[CombineV1ConditionsMigrator()],
)


@pytest.mark.parametrize(
    "x",
    [
        "win",
        "not unix",
        'cuda_compiler_version == "None"',
        "build_platform != target_platform",
    ],
)
def test_is_single_expression(x):
    assert is_single_expression(x)


@pytest.mark.parametrize(
    "x",
    [
        'cuda_compiler_version != "None" and linux"',
        'unix and blas_impl != "mkl"',
        "linux or osx",
        "foo if bar else baz",
    ],
)
def test_not_is_single_expression(x):
    assert not is_single_expression(x)


@pytest.mark.parametrize(
    "a,b",
    [
        ("unix", "not unix"),
        ('cuda_compiler_version == "None"', 'not cuda_compiler_version == "None"'),
        ('cuda_compiler_version == "None"', 'cuda_compiler_version != "None"'),
        ('not cuda_compiler_version == "None"', 'not cuda_compiler_version != "None"'),
    ],
)
def test_is_negated_condition(a, b):
    assert is_negated_condition(a, b)
    assert is_negated_condition(b, a)


@pytest.mark.parametrize(
    "a,b",
    [
        ("not unix", "not unix"),
        ('cuda_compiler_version == "None"', 'not cuda_compiler_version != "None"'),
        ('cuda_compiler_version != "None"', 'not cuda_compiler_version == "None"'),
        ("a or b", "not a or b"),
        ("a and b", "not a and b"),
    ],
)
def test_not_is_negated_condition(a, b):
    assert not is_negated_condition(a, b)
    assert not is_negated_condition(b, a)


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
