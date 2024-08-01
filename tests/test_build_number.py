import pytest

from conda_forge_tick.update_recipe import (
    update_build_number_meta_yaml,
    update_build_number_recipe_yaml,
)


@pytest.mark.parametrize(
    "meta_yaml,new_meta_yaml",
    [
        ("  number: 2", "  number: 0\n"),
        ("    number: 2", "    number: 0\n"),
        ("{% set build_number = 2 %}", "{% set build_number = 0 %}\n"),
        ("{% set build = 2 %}", "{% set build = 0 %}\n"),
    ],
)
def test_update_build_number_meta_yaml(meta_yaml, new_meta_yaml):
    out_meta_yaml = update_build_number_meta_yaml(meta_yaml, 0)
    assert out_meta_yaml == new_meta_yaml


@pytest.mark.parametrize(
    "meta_yaml,new_meta_yaml",
    [
        ("  number: 2", "  number: 3\n"),
        ("    number: 2", "    number: 3\n"),
        ("{% set build_number = 2 %}", "{% set build_number = 3 %}\n"),
        ("{% set build = 2 %}", "{% set build = 3 %}\n"),
    ],
)
def test_update_build_number_meta_yaml_function(meta_yaml, new_meta_yaml):
    out_meta_yaml = update_build_number_meta_yaml(meta_yaml, lambda x: x + 1)
    assert out_meta_yaml == new_meta_yaml


RECIPE_YAML_IN_CONTEXT_1 = """\
context:
  build_number: 100
build:
  number: ${{ build_number }}
"""

RECIPE_YAML_EXP_CONTEXT_1 = """\
context:
  build_number: 101
build:
  number: ${{ build_number }}
"""

RECIPE_YAML_IN_CONTEXT_2 = """\
context:
  build: 100
build:
  number: ${{ build }}
"""

RECIPE_YAML_EXP_CONTEXT_2 = """\
context:
  build: 101
build:
  number: ${{ build }}
"""

RECIPE_YAML_IN_LITERAL = """\
build:
  number: 100
"""

RECIPE_YAML_EXP_LITERAL = """\
build:
  number: 101
"""


@pytest.mark.parametrize(
    "recipe_yaml,expected_recipe_yaml",
    [
        (RECIPE_YAML_IN_CONTEXT_1, RECIPE_YAML_EXP_CONTEXT_1),
        (RECIPE_YAML_IN_CONTEXT_2, RECIPE_YAML_EXP_CONTEXT_2),
        (RECIPE_YAML_IN_LITERAL, RECIPE_YAML_EXP_LITERAL),
    ],
)
def test_update_build_number_recipe_yaml(recipe_yaml, expected_recipe_yaml):
    out_recipe_yaml = update_build_number_recipe_yaml(recipe_yaml, 101)
    assert out_recipe_yaml == expected_recipe_yaml


@pytest.mark.parametrize(
    "recipe_yaml,expected_recipe_yaml",
    [
        (RECIPE_YAML_IN_CONTEXT_1, RECIPE_YAML_EXP_CONTEXT_1),
        (RECIPE_YAML_IN_CONTEXT_2, RECIPE_YAML_EXP_CONTEXT_2),
        (RECIPE_YAML_IN_LITERAL, RECIPE_YAML_EXP_LITERAL),
    ],
)
def test_update_build_number_recipe_yaml_function(recipe_yaml, expected_recipe_yaml):
    out_recipe_yaml = update_build_number_recipe_yaml(recipe_yaml, lambda x: x + 1)
    assert out_recipe_yaml == expected_recipe_yaml
