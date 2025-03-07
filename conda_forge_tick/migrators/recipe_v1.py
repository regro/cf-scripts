import dataclasses
import logging
import os
from pathlib import Path
import typing
from typing import Any, Generator

from conda_forge_tick.migrators.core import MiniMigrator

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ConditionClause:
    # "then" / "else"
    name: str
    # if True, we are currently reading inside the clause
    collecting: bool = False
    # if True, at least the heading was printed already
    printed: bool = False
    # remaining items (not printed yet)
    items: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class ConditionState:
    # complete line with the condition
    condition: str
    # base indent for the condition (i.e. up to "- if")
    indent: str
    # either "then" or "else" if it was printed last, or None if nothing was printed yet
    last_clause_printed: str | None = None
    # the data for then/else clauses
    thens: ConditionClause = dataclasses.field(
        default_factory=lambda: ConditionClause("then")
    )
    elses: ConditionClause = dataclasses.field(
        default_factory=lambda: ConditionClause("else")
    )


class CombineV1ConditionsMigrator(MiniMigrator):
    allowed_schema_versions = [1]
    post_migration = True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        recipe_path = Path(recipe_dir) / "recipe.yaml"
        recipe = recipe_path.read_text().splitlines()

        def flush_clause(
            clause: ConditionClause, condition: ConditionState
        ) -> Generator[str, None, None]:
            """Print pending items from the clause"""
            if clause.items:
                if not clause.printed and len(clause.items) == 1:
                    yield f"{condition.indent}{clause.name}: {clause.items[0]}\n"
                else:
                    if not clause.printed:
                        yield f"{condition.indent}{clause.name}:\n"
                    for subline in clause.items:
                        yield f"{condition.indent}  - {subline}\n"
                clause.printed = True
                condition.last_clause_printed = clause.name
            clause.items.clear()

        def process_clause(
            line: str,
            clause: ConditionClause,
            other: ConditionClause,
            condition: ConditionState,
        ) -> Generator[str, None, None]:
            """Process the line starting a clause"""
            if other.printed:
                yield from flush_clause(other, condition)
            clause.collecting = True
            other.collecting = False
            after = line.split(f"{clause.name}:", 1)[1].strip()
            if after:
                clause.items.append(after)
            else:
                clause.printed = True
                condition.last_clause_printed = clause.name
                yield f"{line}\n"

        def process(recipe: list[str]) -> Generator[str, None, None]:
            # stack of nested conditions
            conditions: list[ConditionState] = []

            for line_no, line in enumerate(recipe):
                if conditions:
                    condition = conditions[-1]
                    if line.startswith(condition.indent):
                        if line.lstrip().startswith("- if:"):
                            # a nested condition
                            indent = line.split("-")[0] + "  "
                            conditions.append(ConditionState(line, indent))
                            yield f"{line}\n"
                        elif line.lstrip().startswith("then:"):
                            yield from process_clause(
                                line, condition.thens, condition.elses, condition
                            )
                        elif line.lstrip().startswith("else:"):
                            yield from process_clause(
                                line, condition.elses, condition.thens, condition
                            )
                        elif line.lstrip().startswith("-"):
                            assert not (
                                condition.thens.collecting
                                and condition.elses.collecting
                            )
                            if condition.thens.collecting:
                                condition.thens.items.append(
                                    line.split("-", 1)[1].strip()
                                )
                            elif condition.elses.collecting:
                                condition.elses.items.append(
                                    line.split("-", 1)[1].strip()
                                )
                            else:
                                raise RuntimeError(
                                    f"then/else expected on line {line_no+1}"
                                )
                        else:
                            raise RuntimeError(
                                f"then/else/list item expected on {line_no+1}"
                            )
                        continue

                    # we have left the previous condition
                    # if we haven't printed "else" yet, we can combine with the next one
                    if (
                        line.startswith(condition.condition)
                        and condition.last_clause_printed != "else"
                    ):
                        conditions[-1].thens.collecting = False
                        conditions[-1].elses.collecting = False
                        continue

                    # prefer then/else order, unless we printed "else" already
                    clause_order = [condition.thens, condition.elses]
                    if condition.elses.printed:
                        clause_order.reverse()
                    for clause in clause_order:
                        yield from flush_clause(clause, condition)
                    conditions.pop()

                # a top-level condition
                if line.lstrip().startswith("- if:"):
                    indent = line.split("-")[0] + "  "
                    conditions.append(ConditionState(line, indent))
                    yield f"{line}\n"
                    continue

                # lines outside a condition
                yield f"{line}\n"

        recipe_path.write_text("".join(process(recipe)))
