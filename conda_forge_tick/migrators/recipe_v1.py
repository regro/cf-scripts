import logging
import typing
from pathlib import Path
from typing import Any

from jinja2 import Environment
from jinja2.nodes import Compare, Node, Not
from jinja2.parser import Parser

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.recipe_parser._parser import _get_yaml_parser

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)


def get_condition(node: Any) -> Node | None:
    if isinstance(node, dict) and "if" in node:
        return Parser(
            Environment(), node["if"].strip(), state="variable"
        ).parse_expression()
    return None


def is_same_condition(a: Node, b: Node) -> bool:
    return a == b


INVERSE_OPS = {
    "eq": "ne",
    "ne": "eq",
    "gt": "lteq",
    "gteq": "lt",
    "lt": "gteq",
    "lteq": "gt",
    "in": "notin",
    "notin": "in",
}


def is_negated_condition(a: Node, b: Node) -> bool:
    # X <-> not X
    if Not(a) == b or a == Not(b):
        return True

    # unwrap (not X) <-> (not Y)
    if isinstance(a, Not) and isinstance(b, Not):
        a = a.node
        b = b.node

    # A == B <-> A != B
    if (
        isinstance(a, Compare)
        and isinstance(b, Compare)
        and len(a.ops) == len(b.ops) == 1
        and a.expr == b.expr
        and a.ops[0].expr == b.ops[0].expr
        and a.ops[0].op == INVERSE_OPS[b.ops[0].op]
    ):
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
