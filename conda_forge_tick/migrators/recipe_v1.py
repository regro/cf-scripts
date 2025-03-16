import logging
import typing
from pathlib import Path
from typing import Any

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.recipe_parser._parser import _get_yaml_parser

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)


def combine_conditions(node):
    """Breadth first recursive call to combine list conditions"""

    # recursion is breadth first because we go through each element here
    # before calling `combine_conditions` on any element in the node
    if isinstance(node, list):
        # 1. loop through list elements, gather the if conditions

        # condition ("if:") -> [(then, else), (then, else)...]
        conditions = {}

        for i in node:
            if isinstance(i, dict) and "if" in i:
                conditions.setdefault(i["if"], []).append((i["then"], i.get("else")))

        # 2. if elements share a compatible if condition
        # combine their if...then...else statements
        to_drop = []
        for i in range(len(node)):
            if isinstance(node[i], dict) and "if" in node[i]:
                condition = node[i]["if"]
                if condition not in conditions:
                    # already combined it, so drop the repeat instance
                    to_drop.append(i)
                    continue
                if len(conditions[condition]) > 1:
                    new_then = []
                    new_else = []
                    for sub_then, sub_else in conditions[node[i]["if"]]:
                        if isinstance(sub_then, list):
                            new_then.extend(sub_then)
                        else:
                            assert sub_then is not None
                            new_then.append(sub_then)
                        if isinstance(sub_else, list):
                            new_else.extend(sub_else)
                        elif sub_else is not None:
                            new_else.append(sub_else)
                    node[i]["then"] = new_then
                    if new_else:
                        # TODO: preserve inline "else" instead of converting it to a list?
                        node[i]["else"] = new_else
                    else:
                        assert "else" not in node[i]
                    # remove it from the dict, so we don't output it again
                    del conditions[condition]

        # drop the repeated conditions
        for i in reversed(to_drop):
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
