from pathlib import Path

from conda_forge_tick.utils import _render_recipe_yaml

TEST_RECIPE_YAML_PATH = Path(__file__).parent / "test_recipe_yaml"


def test_render_recipe_yaml():
    text = TEST_RECIPE_YAML_PATH.joinpath("ipywidgets.yaml").read_text()
    data = _render_recipe_yaml(text)
    package_data = data[0]["package"]

    assert package_data["name"] == "ipywidgets"
    assert package_data["version"] == "8.1.2"


def test_parse_validated_recipes():
    assert False
