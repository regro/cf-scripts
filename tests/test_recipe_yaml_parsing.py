import os
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from conda_forge_tick.feedstock_parser import (
    populate_feedstock_attributes,
)
from conda_forge_tick.utils import (
    _parse_recipe_yaml_requirements,
    _process_recipe_for_pinning,
    _render_recipe_yaml,
    parse_meta_yaml,
    parse_munged_run_export,
    parse_recipe_yaml,
)

TEST_RECIPE_YAML_PATH = Path(__file__).parent / "test_recipe_yaml"
TEST_META_YAML_PATH = Path(__file__).parent / "test_yaml"


def test_render_recipe_yaml():
    text = TEST_RECIPE_YAML_PATH.joinpath("ipywidgets.yaml").read_text()
    data = _render_recipe_yaml(text)
    package_data = data[0]["package"]

    assert package_data["name"] == "ipywidgets"
    assert package_data["version"] == "8.1.2"


def test_parse_validated_recipes():
    text = TEST_RECIPE_YAML_PATH.joinpath("mplb.yaml").read_text()
    recipe_yaml_dict = parse_recipe_yaml(text)

    text = TEST_META_YAML_PATH.joinpath("mplb.yaml").read_text()
    meta_yaml_dict = parse_meta_yaml(text)

    for key in ["about", "build", "package", "requirements", "source", "extra"]:
        assert recipe_yaml_dict[key] == meta_yaml_dict[key]


def test_process_recipe_for_pinning():
    input_recipes = [
        {
            "some_key": {
                "pin_subpackage": {"name": "example_package", "upper_bound": "x.x"}
            }
        },
        {
            "another_key": [
                {
                    "pin_compatible": {
                        "name": "another_package",
                        "lower_bound": "x.x.x.x",
                    }
                }
            ]
        },
    ]
    expected_result = [
        {
            "some_key": {
                "pin_subpackage": {
                    "name": "__quote_plus__%7B%27package_name%27%3A+%27example_package%27%2C+%27upper_bound%27%3A+%27x.x%27%7D__quote_plus__"
                },
            }
        },
        {
            "another_key": [
                {
                    "pin_compatible": {
                        "name": "__quote_plus__%7B%27package_name%27%3A+%27another_package%27%2C+%27lower_bound%27%3A+%27x.x.x.x%27%7D__quote_plus__"
                    },
                }
            ]
        },
    ]

    assert _process_recipe_for_pinning(input_recipes) == expected_result


def test_parse_recipe_yaml_requirements_pin_subpackage():
    requirements = {
        "run_exports": {
            "weak": [
                {
                    "pin_subpackage": {
                        "name": "slepc",
                        "lower_bound": "x.x.x.x.x.x",
                        "upper_bound": "x.x",
                    }
                }
            ]
        }
    }

    _parse_recipe_yaml_requirements(requirements)
    assert requirements["run_exports"]["weak"] == ["slepc"]


def test_parse_recipe_yaml_requirements_pin_compatible():
    requirements = {
        "run_exports": {
            "strong": [
                {
                    "pin_compatible": {
                        "name": "slepc",
                        "lower_bound": "x.x.x.x.x.x",
                        "upper_bound": "x.x",
                    }
                }
            ]
        }
    }

    _parse_recipe_yaml_requirements(requirements)
    assert requirements["run_exports"]["strong"] == ["slepc"]


def test_parse_recipe_yaml_requirements_str():
    requirements = {"run_exports": {"weak": ["slepc"]}}

    _parse_recipe_yaml_requirements(requirements)
    assert requirements["run_exports"]["weak"] == ["slepc"]


def test_parse_munged_run_export_slepc():
    recipe = TEST_RECIPE_YAML_PATH.joinpath("slepc.yaml").read_text()
    recipe_yaml = parse_recipe_yaml(
        recipe,
        for_pinning=True,
    )
    assert recipe_yaml["build"]["run_exports"]["weak"] == [
        "__quote_plus__%7B%27package_name%27%3A+%27slepc%27%2C+%27lower_bound%27%3A+%27x.x.x.x.x.x%27%2C+%27upper_bound%27%3A+%27x.x%27%7D__quote_plus__"
    ]

    assert parse_munged_run_export(recipe_yaml["build"]["run_exports"]["weak"][0]) == {
        "package_name": "slepc",
        "lower_bound": "x.x.x.x.x.x",
        "upper_bound": "x.x",
    }


def test_parse_munged_run_export_slepc_weak_strong():
    recipe = TEST_RECIPE_YAML_PATH.joinpath("slepc_weak_strong.yaml").read_text()
    recipe_yaml = parse_recipe_yaml(
        recipe,
        for_pinning=True,
    )
    assert recipe_yaml["build"]["run_exports"]["weak"] == [
        "__quote_plus__%7B%27package_name%27%3A+%27slepc%27%2C+%27lower_bound%27%3A+%27x.x.x.x.x.x%27%2C+%27upper_bound%27%3A+%27x.x%27%7D__quote_plus__"
    ]

    assert recipe_yaml["build"]["run_exports"]["strong"] == [
        "__quote_plus__%7B%27package_name%27%3A+%27slepc%27%2C+%27lower_bound%27%3A+%27x.x.x.x.x.x%27%2C+%27upper_bound%27%3A+%27x%27%7D__quote_plus__"
    ]

    assert parse_munged_run_export(recipe_yaml["build"]["run_exports"]["weak"][0]) == {
        "package_name": "slepc",
        "lower_bound": "x.x.x.x.x.x",
        "upper_bound": "x.x",
    }

    assert parse_munged_run_export(
        recipe_yaml["build"]["run_exports"]["strong"][0]
    ) == {
        "package_name": "slepc",
        "lower_bound": "x.x.x.x.x.x",
        "upper_bound": "x",
    }


@pytest.mark.parametrize("recipe_name", ["libssh", "torchvision-reduced"])
def test_populate_feedstock_attributes(recipe_name):
    """Test parsing different recipe files."""
    recipe_yaml = TEST_RECIPE_YAML_PATH / f"{recipe_name}.yaml"

    with TemporaryDirectory() as tmpdir:
        os.makedirs(Path(tmpdir) / "recipe", exist_ok=True)
        os.makedirs(Path(tmpdir) / ".ci_support", exist_ok=True)
        shutil.copy2(
            TEST_RECIPE_YAML_PATH / f"{recipe_name}.yaml",
            Path(tmpdir) / "recipe" / "recipe.yaml",
        )
        (Path(tmpdir) / ".ci_support" / "linux_64_.yaml").write_text(
            "target_platform:\n - 'linux-64'\ncuda_compiler_version:\n  - 'None'\n"
        )
        existing_attrs = {}
        node_attrs = populate_feedstock_attributes(
            recipe_name,
            existing_attrs,
            recipe_yaml=recipe_yaml.read_text(),
            feedstock_dir=tmpdir,
        )

    assert node_attrs["feedstock_name"] == recipe_name
    for key, value in node_attrs["total_requirements"].items():
        assert isinstance(value, set)
        for el in value:
            assert isinstance(el, str)
