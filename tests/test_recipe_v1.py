from pathlib import Path

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import (
    CombineV1ConditionsMigrator,
    Version,
)
from conda_forge_tick.migrators.recipe_v1 import (
    get_condition,
    get_new_sub_condition,
    is_negated_condition,
    is_sub_condition,
)

YAML_PATH = Path(__file__).parent / "test_v1_yaml"

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
combine_conditions_migrator = Version(
    set(),
    piggy_back_migrations=[CombineV1ConditionsMigrator()],
    total_graph=TOTAL_GRAPH,
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


@pytest.mark.parametrize(
    "sub_cond,super_cond,new_sub",
    [
        (
            "build_platform != target_platform and megabuild",
            "build_platform != target_platform",
            "megabuild",
        ),
        (
            "build_platform != target_platform and not megabuild",
            "build_platform != target_platform",
            "not megabuild",
        ),
        (
            'cuda_compiler_version != "None" and linux',
            'cuda_compiler_version != "None"',
            "linux",
        ),
        (
            'linux and cuda_compiler_version != "None"',
            'cuda_compiler_version != "None"',
            "linux",
        ),
        ("a and b", "a", "b"),
        ("a and b", "b", "a"),
        ("(a or b) and c", "c", "a or b"),
        ("(a or b) and c", "(a or b)", "c"),
        ("(a or b) and (c or d)", "(a or b)", "c or d"),
        ("(a or b) and (c or d)", "(c or d)", "a or b"),
        ("(a or b) and c", "a or b", "c"),
        ("(a or b) and (c or d)", "a or b", "c or d"),
        ("(a or b) and (c or d)", "c or d", "a or b"),
        ("a and b and c", "a and b", "c"),
        ("a and b and c", "c", "a and b"),
        ("a and (b and c)", "a", "b and c"),
        ("a and (b and c)", "(b and c)", "a"),
        ("a and (b and c)", "b and c", "a"),
    ],
)
def test_sub_condition(sub_cond, super_cond, new_sub):
    sub_node = get_condition({"if": sub_cond})
    super_node = get_condition({"if": super_cond})
    assert is_sub_condition(sub_node=sub_node, super_node=super_node)
    assert not is_sub_condition(sub_node=super_node, super_node=sub_node)
    assert get_new_sub_condition(sub_cond=sub_cond, super_cond=super_cond) == new_sub
    assert get_new_sub_condition(sub_cond=super_cond, super_cond=sub_cond) is None


@pytest.mark.parametrize(
    "sub_cond,super_cond",
    [
        ("a or b and c", "a"),
        ("a or b and c", "c"),
        # jinja2 interprets this as (a and b) and c, but we handle only
        # the top-most node
        ("a and b and c", "a"),
        ("a and b and c", "b and c"),
        ("a and bar", "a and b"),
        ("not (a and b)", "a and b"),
    ],
)
def test_not_sub_condition(sub_cond, super_cond):
    sub_node = get_condition({"if": sub_cond})
    super_node = get_condition({"if": super_cond})
    assert not is_sub_condition(sub_node=sub_node, super_node=super_node)
    assert not is_sub_condition(sub_node=super_node, super_node=sub_node)


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
