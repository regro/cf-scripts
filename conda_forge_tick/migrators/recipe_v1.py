import logging
import typing
from pathlib import Path
from typing import Any

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.recipe_parser._parser import _get_yaml_parser

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)


def is_same_condition(a: Any, b: Any) -> bool:
    return (
        isinstance(a, dict)
        and isinstance(b, dict)
        and "if" in a
        and "if" in b
        and a["if"] == b["if"]
    )


def fold_branch(source: Any, dest: Any, branch: str) -> None:
    if branch not in source:
        return
    source_l = source[branch]
    if isinstance(source_l, str):
        source_l = [source_l]

    if branch not in dest:
        dest[branch] = []
    elif isinstance(dest[branch], str):
        dest[branch] = [dest[branch]]
    dest[branch].extend(source_l)


def combine_conditions(node: Any):
    """Breadth first recursive call to combine list conditions"""

    # recursion is breadth first because we go through each element here
    # before calling `combine_conditions` on any element in the node
    if isinstance(node, list):
        # iterate in reverse order, so we can remove elements on the fly
        # start at index 1, since we can only fold to the previous node
        for i in reversed(range(1, len(node))):
            if is_same_condition(node[i], node[i - 1]):
                fold_branch(node[i], node[i - 1], "then")
                fold_branch(node[i], node[i - 1], "else")
                del node[i]

    # then we descend down the tree
    if isinstance(node, dict):
        for k, v in node.items():
            if k != "if":  # don't combine if statements
                node[k] = combine_conditions(v)
    elif isinstance(node, list):
        for i in range(len(node)):
            node[i] = combine_conditions(node[i])

    return node


class CombineV1ConditionsMigrator(MiniMigrator):
    allowed_schema_versions = [1]
    post_migration = True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        recipe_path = Path(recipe_dir) / "recipe.yaml"
        parser = _get_yaml_parser(typ="rt")
        with recipe_path.open() as f:
            yaml = parser.load(f)

        yaml = combine_conditions(yaml)

        with recipe_path.open("w") as f:
            parser.dump(yaml, f)
