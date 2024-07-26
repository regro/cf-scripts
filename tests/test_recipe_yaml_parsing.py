from pathlib import Path

from conda_forge_tick.utils import (
    _render_recipe_yaml,
    parse_meta_yaml,
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
