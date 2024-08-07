from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal
from conda_forge_tick.update_recipe.v2.yaml import _load_yaml, _dump_yaml_to_str
if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

HashType = Literal["md5", "sha256"]


def _update_build_number_in_context(recipe: dict[str, Any], new_build_number: int) -> bool:
    for key in recipe.get("context", {}):
        if key.startswith("build_") or key == "build":
            recipe["context"][key] = new_build_number
            return True
    return False


def _update_build_number_in_recipe(recipe: dict[str, Any], new_build_number: int) -> bool:
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


def update_build_number(file: Path, new_build_number: int = 0) -> str:
    """
    Update the build number in the recipe file.

    Arguments:
    ----------
    * `file` - The path to the recipe file.
    * `new_build_number` - The new build number to use. (default: 0)

    Returns:
    --------
    The updated recipe as a string.
    """
    data = _load_yaml(file)
    build_number_modified = _update_build_number_in_context(data, new_build_number)
    if not build_number_modified:
        _update_build_number_in_recipe(data, new_build_number)

    return _dump_yaml_to_str(data)
