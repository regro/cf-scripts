import pytest

from conda_forge_tick.update_recipe import update_build_number


@pytest.mark.parametrize(
    "meta_yaml,new_meta_yaml",
    [
        ("  number: 2", "  number: 0\n"),
        ("    number: 2", "    number: 0\n"),
        ("{% set build_number = 2 %}", "{% set build_number = 0 %}\n"),
        ("{% set build = 2 %}", "{% set build = 0 %}\n"),
    ],
)
def test_update_build_number(meta_yaml, new_meta_yaml):
    out_meta_yaml = update_build_number(meta_yaml, 0)
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
def test_update_build_number_function(meta_yaml, new_meta_yaml):
    out_meta_yaml = update_build_number(meta_yaml, lambda x: x + 1)
    assert out_meta_yaml == new_meta_yaml
