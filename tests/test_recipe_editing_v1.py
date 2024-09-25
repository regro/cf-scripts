from pathlib import Path

import pytest

from conda_forge_tick.update_recipe.v1_recipe import update_build_number


@pytest.fixture
def data_dir() -> Path:
    return Path(__file__).parent / "recipe_v1"


def test_build_number_mod(data_dir: Path) -> None:
    tests = data_dir / "build_number"
    result = update_build_number(tests / "test_1/recipe.yaml", 0)
    expected = tests / "test_1/expected.yaml"
    assert result == expected.read_text()

    result = update_build_number(tests / "test_2/recipe.yaml", 0)
    expected = tests / "test_2/expected.yaml"
    assert result == expected.read_text()
