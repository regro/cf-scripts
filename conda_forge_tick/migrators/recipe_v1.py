import logging
import typing
from pathlib import Path
from typing import Any

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.recipe_parser._parser import _get_yaml_parser

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)


def get_condition(node: Any) -> str | None:
    if isinstance(node, dict) and "if" in node:
        return node["if"].strip()
    return None


def is_same_condition(a: str, b: str) -> bool:
    return a == b


def is_single_expression(condition: str) -> bool:
    return not any(f" {x} " in condition for x in ("and", "or", "if"))


def is_negated_condition(a: str, b: str) -> bool:
    # we only handle negating trivial expressions
    if not all(map(is_single_expression, (a, b))):
        return False

    # X <-> not X
    a_not = a.startswith("not")
    b_not = b.startswith("not")
    if (
        a_not != b_not
        and a.removeprefix("not").lstrip() == b.removeprefix("not").lstrip()
    ):
        return True

    # A == B <-> A != B
    if a == b.replace("==", "!=") or a == b.replace("!=", "=="):
        return True

    return False


def fold_branch(source: Any, dest: Any, branch: str, dest_branch: str) -> None:
    if branch not in source:
        return

    source_l = source[branch]
    if isinstance(source_l, str):
        if dest_branch not in dest:
            # special-case: do not expand a single string to list
            dest[dest_branch] = source_l
            return
        source_l = [source_l]

    if dest_branch not in dest:
        dest[dest_branch] = []
    elif isinstance(dest[dest_branch], str):
        dest[dest_branch] = [dest[dest_branch]]
    dest[dest_branch].extend(source_l)


def combine_conditions(node: Any):
    """Breadth first recursive call to combine list conditions"""

    # recursion is breadth first because we go through each element here
    # before calling `combine_conditions` on any element in the node
    if isinstance(node, list):
        # iterate in reverse order, so we can remove elements on the fly
        # start at index 1, since we can only fold to the previous node
        for i in reversed(range(1, len(node))):
            node_cond = get_condition(node[i])
            prev_cond = get_condition(node[i - 1])
            if node_cond is None or prev_cond is None:
                continue

            if is_same_condition(node_cond, prev_cond):
                fold_branch(node[i], node[i - 1], "then", "then")
                fold_branch(node[i], node[i - 1], "else", "else")
                del node[i]
            elif is_negated_condition(node_cond, prev_cond):
                fold_branch(node[i], node[i - 1], "then", "else")
                fold_branch(node[i], node[i - 1], "else", "then")
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
