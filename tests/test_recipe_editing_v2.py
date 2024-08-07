import pytest
from pathlib import Path

from conda_forge_tick.recipe_editing_v2 import update_build_number, update_version


@pytest.fixture
def data_dir() -> Path:
    return Path(__file__).parent / "recipe_v2"

def test_build_number_mod(data_dir: Path) -> None:
    tests = data_dir / "build_number"
    result = update_build_number(tests / "test_1/recipe.yaml", 0)
    expected = tests / "test_1/expected.yaml"
    assert result == expected.read_text()

    result = update_build_number(tests / "test_2/recipe.yaml", 0)
    expected = tests / "test_2/expected.yaml"
    assert result == expected.read_text()


def test_version_mod(data_dir: Path) -> None:
    tests = data_dir / "version"
    test_recipes = [tests / "test_1/recipe.yaml", tests / "test_2/recipe.yaml"]
    for recipe in test_recipes:
        result = update_version(recipe, "0.25.0", None)
        expected = recipe.parent / "expected.yaml"
        assert result == expected.read_text()

    test_python = tests / "test_3/recipe.yaml"
    result = update_version(test_python, "1.9.0", None)
    expected = test_python.parent / "expected.yaml"
    assert result == expected.read_text()

    test_cran = tests / "test_4/recipe.yaml"
    result = update_version(test_cran, "1.1-30", None)
    expected = test_cran.parent / "expected.yaml"
    assert result == expected.read_text()
