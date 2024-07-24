from pathlib import Path

from conda_forge_tick.utils import (
    _render_recipe_yaml,
    parse_meta_yaml_local,
    parse_recipe_yaml_local,
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
    recipe_yaml_dict = parse_recipe_yaml_local(text)

    text = TEST_META_YAML_PATH.joinpath("mplb.yaml").read_text()
    meta_yaml_dict = parse_meta_yaml_local(text)

    assert recipe_yaml_dict["about"] == meta_yaml_dict["about"]
    assert recipe_yaml_dict["build"] == meta_yaml_dict["build"]
    assert recipe_yaml_dict["package"] == meta_yaml_dict["package"]
    assert recipe_yaml_dict["requirements"] == meta_yaml_dict["requirements"]
    assert recipe_yaml_dict["source"] == meta_yaml_dict["source"]
