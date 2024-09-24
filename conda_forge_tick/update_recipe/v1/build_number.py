from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Callable, Literal

from conda_forge_tick.update_recipe.v1.yaml import _dump_yaml_to_str, _load_yaml

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

HashType = Literal["md5", "sha256"]

RE_PATTERN = re.compile(r"(?:build|build_number|number):\s*(\d+)")


def old_build_number(recipe_text: str) -> int:
    """
    Extract the build number from the recipe text.

    Arguments:
    ----------
    * `recipe_text` - The recipe text.

    Returns:
    --------
    * The build number.
    """
    match = re.search(RE_PATTERN, recipe_text)
    if match is not None:
        return int(match.group(1))
    return 0


def _update_build_number_in_context(
    recipe: dict[str, Any], new_build_number: int
) -> bool:
    for key in recipe.get("context", {}):
        if key.startswith("build_") or key == "build":
            recipe["context"][key] = new_build_number
            return True
    return False


def _update_build_number_in_recipe(
    recipe: dict[str, Any], new_build_number: int
) -> bool:
    is_modified = False
    if "build" in recipe and "number" in recipe["build"]:
        recipe["build"]["number"] = new_build_number
        is_modified = True

    if "outputs" in recipe:
        for output in recipe["outputs"]:
            if "build" in output and "number" in output["build"]:
                output["build"]["number"] = new_build_number
                is_modified = True

    return is_modified


def update_build_number(file: Path, new_build_number: int | Callable = 0) -> str:
    """
    Update the build number in the recipe file.

    Arguments:
    ----------
    * `file` - The path to the recipe file.
    * `new_build_number` - The new build number to use. (default: 0)

    Returns:
    --------
    * The updated recipe as a string.
    """
    data = _load_yaml(file)

    if callable(new_build_number):
        detected_build_number = old_build_number(file.read_text())
        new_build_number = new_build_number(detected_build_number)

    build_number_modified = _update_build_number_in_context(data, new_build_number)

    if not build_number_modified:
        _update_build_number_in_recipe(data, new_build_number)

    return _dump_yaml_to_str(data)
