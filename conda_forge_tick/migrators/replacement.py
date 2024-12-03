import logging
import os
import re
import typing
from typing import Any

import networkx as nx

from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.migrators.core import Migrator

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict, MigrationUidTypedDict, PackageName


logger = logging.getLogger(__name__)


class Replacement(Migrator):
    """Migrator for replacing one package with another.

    Parameters
    ----------
    old_pkg : str
        The package to be replaced.
    new_pkg : str
        The package to replace the `old_pkg`.
    rationale : str
        The reason the for the migration. Should be a full statement.
    graph : nx.DiGraph, optional
        The graph of feedstocks.
    pr_limit : int, optional
        The maximum number of PRs made per run of the bot.
    check_solvable : bool, optional
        If True, uses mamba to check if the final recipe is solvable.
    """

    migrator_version = 0
    rerender = True

    def __init__(
        self,
        *,
        old_pkg: "PackageName",
        new_pkg: "PackageName",
        rationale: str,
        graph: nx.DiGraph = None,
        pr_limit: int = 0,
        check_solvable=True,
        effective_graph: nx.DiGraph = None,
    ):
        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "old_pkg": old_pkg,
                "new_pkg": new_pkg,
                "rationale": rationale,
                "graph": graph,
                "pr_limit": pr_limit,
                "check_solvable": check_solvable,
                "effective_graph": effective_graph,
            }

        super().__init__(
            pr_limit,
            check_solvable=check_solvable,
            graph=graph,
            effective_graph=effective_graph,
        )
        self.old_pkg = old_pkg
        self.new_pkg = new_pkg
        self.pattern = re.compile(r"\s*-\s*(%s)(\s+|$)" % old_pkg)
        self.packages = {old_pkg}
        self.rationale = rationale
        self.name = f"{old_pkg}-to-{new_pkg}"

        self._reset_effective_graph()

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        requirements = attrs.get("requirements", {})
        rq = (
            requirements.get("build", set())
            | requirements.get("host", set())
            | requirements.get("run", set())
            | requirements.get("test", set())
        )
        return super().filter(attrs) or len(rq & self.packages) == 0

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        with open(os.path.join(recipe_dir, "meta.yaml")) as f:
            raw = f.read()
        lines = raw.splitlines()
        n = False
        for i, line in enumerate(lines):
            m = self.pattern.match(line)
            if m is not None:
                lines[i] = lines[i].replace(m.group(1), self.new_pkg)
                n = True
        if not n:
            return False
        upd = "\n".join(lines) + "\n"
        with open(os.path.join(recipe_dir, "meta.yaml"), "w") as f:
            f.write(upd)
        self.set_build_number(os.path.join(recipe_dir, "meta.yaml"))
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: ClonedFeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            """\
I noticed that this recipe depends on `{}` instead of `{}`. {} Thus I made this PR.

Notes and instructions for merging this PR:
1. Make sure that the recipe can indeed only depend on `{}`.
2. Please merge the PR only after the tests have passed.
3. Feel free to push to the bot's branch to update this PR if \
needed.""".format(self.old_pkg, self.new_pkg, self.rationale, self.new_pkg),
        )
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return f"use {self.new_pkg} instead of {self.old_pkg}"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return f"Suggestion: depend on {self.new_pkg} instead of {self.old_pkg}"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return f"{self.old_pkg}-to-{self.new_pkg}-migration-{self.migrator_version}"

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        n = super().migrator_uid(attrs)
        n["name"] = self.name
        return n
