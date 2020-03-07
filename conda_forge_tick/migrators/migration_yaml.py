import os
from itertools import chain
import typing
from typing import Optional, Set, Sequence, Any
import time

import networkx as nx
import ruamel.yaml as yaml

from conda_forge_tick.contexts import FeedstockContext
from conda_forge_tick.migrators.core import GraphMigrator, MiniMigrator, \
    Migrator
from conda_forge_tick.xonsh_utils import eval_xonsh, indir

if typing.TYPE_CHECKING:
    from ..migrators_types import *


class MigrationYaml(GraphMigrator):
    """Migrator for bumping the build number."""

    migrator_version = 0
    rerender = True

    # TODO: add a description kwarg for the status page at some point.
    # TODO: make yaml_contents an arg?
    def __init__(
        self,
        yaml_contents: str,
        graph: nx.DiGraph = None,
        name: Optional[str] = None,
        pr_limit: int = 50,
        top_level: Set["PackageName"] = None,
        cycles: Optional[Sequence["PackageName"]] = None,
        migration_number: Optional[int] = None,
        bump_number: int = 1,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
        **kwargs: Any,
    ):
        super().__init__(
            graph=graph,
            pr_limit=pr_limit,
            obj_version=migration_number,
            piggy_back_migrations=piggy_back_migrations,
        )
        self.yaml_contents = yaml_contents
        assert isinstance(name, str)
        self.name: str = name
        self.top_level = top_level or set()
        self.cycles = set(chain.from_iterable(cycles or []))

        # auto set the pr_limit for initial things
        number_pred = len(
            [
                k
                for k, v in self.graph.nodes.items()
                if self.migrator_uid(v.get("payload", {}))
                in [vv.get("data", {}) for vv in v.get("payload", {}).get("PRed", [])]
            ],
        )
        if number_pred == 0:
            self.pr_limit = 2
        elif number_pred < 7:
            self.pr_limit = 5
        self.bump_number = bump_number
        print(self.yaml_contents)

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        # in case the render is old
        os.makedirs(os.path.join(recipe_dir, "../.ci_support"), exist_ok=True)
        with indir(os.path.join(recipe_dir, "../.ci_support")):
            os.makedirs("migrations", exist_ok=True)
            with indir("migrations"):
                with open(f"{self.name}.yaml", "w") as f:
                    f.write(self.yaml_contents)
                eval_xonsh("git add .")
        with indir(recipe_dir):
            self.set_build_number("meta.yaml")
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: "FeedstockContext") -> str:
        body = super().pr_body(feedstock_ctx)
        additional_body = (
            "This PR has been triggered in an effort to update **{name}**.\n\n"
            "Notes and instructions for merging this PR:\n"
            "1. Please merge the PR only after the tests have passed. \n"
            "2. Feel free to push to the bot's branch to update this PR if needed. \n\n"
            "**Please note that if you close this PR we presume that "
            "the feedstock has been rebuilt, so if you are going to "
            "perform the rebuild yourself don't close this PR until "
            "the your rebuild has been merged.**\n\n"
            "This package has the following downstream children:\n"
            "{children}\n"
            "And potentially more."
            "".format(
                name=self.name,
                children="\n".join(self.downstream_children(feedstock_ctx)),
            )
        )
        body = body.format(additional_body)
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        if self.name:
            return "Rebuild for " + self.name
        else:
            return "Bump build number"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        if self.name:
            return "Rebuild for " + self.name
        else:
            return "Bump build number"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        s_obj = str(self.obj_version) if self.obj_version else ""
        return f"rebuild-{self.name.lower().replace(' ', '_')}-{self.migrator_version}-{s_obj}"

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        n = super().migrator_uid(attrs)
        n["name"] = self.name
        return n

    def order(
        self, graph: nx.DiGraph, total_graph: nx.DiGraph,
    ) -> Sequence["PackageName"]:
        """Run the order by number of decendents, ties are resolved by package name"""
        return sorted(
            graph, key=lambda x: (len(nx.descendants(total_graph, x)), x), reverse=True,
        )


class MigrationYamlCreator(Migrator):
    """Migrator creating migration yaml files."""

    migrator_version = 0
    rerender = False

    # TODO: add a description kwarg for the status page at some point.
    # TODO: make yaml_contents an arg?
    def __init__(
            self,
            package_name: str,
            pin_version: str,
            pr_limit: int = 1,
            **kwargs: Any,
    ):
        super().__init__(
            pr_limit=pr_limit,
        )
        self.pin_version = pin_version
        self.package_name = package_name

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        if attrs['name'] == 'conda-forge-pinning':
            return False
        return True

    def migrate(
            self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        migration_yaml_dict = {'__migrator': {'build_number': 1,
                                              'kind': 'version',
                                              'migration_number': 1},
                               self.package_name: [self.pin_version],
                               'migrator_ts': f'{time.time():.0f}'}
        with indir(os.path.join(recipe_dir, "migrations")):
            with open(f"{self.package_name}{self.pin_version}.yaml", "w") as f:
                yaml.dump(migration_yaml_dict, f)
                eval_xonsh("git add .")
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: "FeedstockContext") -> str:
        body = super().pr_body(feedstock_ctx)
        additional_body = (
            "This PR has been triggered in an effort to update the pin for"
            " **{name}**.\n\n"
            "Notes and instructions for merging this PR:\n"
            "1. Please merge the PR only if this new version is to be a "
            "supported pin. \n"
            "2. Feel free to push to the bot's branch to update this PR if "
            "needed. \n\n"
            "**Please note that if you close this PR we presume that "
            "the new pin has been rejected."
            "".format(
                name=self.package_name,
            )
        )
        body = body.format(additional_body)
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return f"Update pin for {self.package_name}"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return f"Update pin for {self.package_name}"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        s_obj = str(self.obj_version) if self.obj_version else ""
        return f"new_pin-{self.package_name.lower().replace(' ', '_')}-" \
               f"{self.pin_version}-{self.migrator_version}-{s_obj}"

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        n = super().migrator_uid(attrs)
        n["name"] = self.package_name
        n["pin_version"] = self.pin_version
        return n

    def order(
            self, graph: nx.DiGraph, total_graph: nx.DiGraph,
    ) -> Sequence["PackageName"]:
        """Run the order by number of decendents, ties are resolved by package name"""
        return sorted(
            graph, key=lambda x: (len(nx.descendants(total_graph, x)), x),
            reverse=True,
        )
