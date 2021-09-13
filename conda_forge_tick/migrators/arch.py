from textwrap import dedent
import typing
from typing import Optional, Any, Sequence

import networkx as nx

from conda_forge_tick.contexts import FeedstockContext
from conda_forge_tick.migrators.core import _sanitized_muids, GraphMigrator
from conda_forge_tick.utils import (
    frozen_to_json_friendly,
    pluck,
    as_iterable,
    yaml_safe_load,
    yaml_safe_dump,
)
from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.make_graph import get_deps_from_outputs_lut
from .migration_yaml import all_noarch

if typing.TYPE_CHECKING:
    from conda_forge_tick.migrators_types import AttrsTypedDict, MigrationUidTypedDict

from .core import MiniMigrator


class ArchRebuild(GraphMigrator):
    """
    A Migrator that add aarch64 and ppc64le builds to feedstocks
    """

    migrator_version = 1
    rerender = True
    # We purposefully don't want to bump build number for this migrator
    bump_number = 0
    ignored_packages = {
        "make",
        "perl",
        "toolchain",
        "posix",
        "patchelf",  # weird issue
    }
    arches = {
        "linux_aarch64": "default",
        "linux_ppc64le": "default",
    }

    def __init__(
        self,
        graph: nx.DiGraph = None,
        name: Optional[str] = None,
        pr_limit: int = 0,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
    ):
        # rebuild the graph to only use edges from the arm and power requirements
        graph2 = nx.create_empty_copy(graph)
        for node, attrs in graph.nodes(data="payload"):
            for plat_arch in self.arches:
                deps = set().union(
                    *attrs.get(
                        f"{plat_arch}_requirements",
                        attrs.get("requirements", {}),
                    ).values()
                )
                for dep in get_deps_from_outputs_lut(deps, graph.graph["outputs_lut"]):
                    graph2.add_edge(dep, node)

        super().__init__(
            graph=graph2,
            pr_limit=pr_limit,
            check_solvable=False,
            piggy_back_migrations=piggy_back_migrations,
        )

        assert not self.check_solvable, "We don't want to check solvability for aarch!"
        # We are constraining the scope of this migrator
        with indir("../conda-forge-pinning-feedstock/recipe/migrations"), open(
            "arch_rebuild.txt",
        ) as f:
            self.target_packages = set(f.read().split())

        self.name = name
        # filter the graph down to the target packages
        if self.target_packages:
            self.target_packages.add("python")  # hack that is ~harmless?
            packages = self.target_packages.copy()
            for target in self.target_packages:
                if target in self.graph.nodes:
                    packages.update(nx.ancestors(self.graph, target))
            self.graph.remove_nodes_from([n for n in self.graph if n not in packages])

        # filter out stub packages and ignored packages
        for node, attrs in list(self.graph.nodes("payload")):
            if (
                node.endswith("_stub")
                or (node.startswith("m2-"))
                or (node.startswith("m2w64-"))
                or (node in self.ignored_packages)
                or all_noarch(attrs)
            ):
                pluck(self.graph, node)
        self.graph.remove_edges_from(nx.selfloop_edges(self.graph))

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        if super().filter(attrs):
            return True
        muid = frozen_to_json_friendly(self.migrator_uid(attrs))
        for arch in self.arches:
            configured_arch = (
                attrs.get("conda-forge.yml", {}).get("provider", {}).get(arch)
            )
            if configured_arch:
                return muid in _sanitized_muids(attrs.get("PRed", []))
        else:
            return False

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        with indir(recipe_dir + "/.."):
            self.set_build_number("recipe/meta.yaml")
            with open("conda-forge.yml") as f:
                y = yaml_safe_load(f)
            if "provider" not in y:
                y["provider"] = {}
            for k, v in self.arches.items():
                if k not in y["provider"]:
                    y["provider"][k] = v

            with open("conda-forge.yml", "w") as f:
                yaml_safe_dump(y, f)

        return super().migrate(recipe_dir, attrs, **kwargs)

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return "Arch Migrator"

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            dedent(
                """\
        This feedstock is being rebuilt as part of the aarch64/ppc64le migration.

        **Feel free to merge the PR if CI is all green, but please don't close it
        without reaching out the the ARM migrators first at @conda-forge/arm-arch.**
        """,
            ),
        )
        return body

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return super().remote_branch(feedstock_ctx) + "_arch"


class OSXArm(GraphMigrator):
    """
    A Migrator that add arm osx builds to feedstocks
    """

    migrator_version = 1
    rerender = True
    # We purposefully don't want to bump build number for this migrator
    bump_number = 0

    ignored_packages = set()
    excluded_dependencies = set()

    arches = ["osx_arm64"]

    additional_keys = {
        "build_platform": {"osx_arm64": "osx_64"},
        "test_on_native_only": True,
    }

    def __init__(
        self,
        graph: nx.DiGraph = None,
        name: Optional[str] = None,
        pr_limit: int = 0,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
    ):
        # rebuild the graph to only use edges from the arm osx requirements
        graph2 = nx.create_empty_copy(graph)
        for node, attrs in graph.nodes(data="payload"):
            for plat_arch in self.arches:
                reqs = attrs.get(
                    f"{plat_arch}_requirements",
                    attrs.get("osx_64_requirements", attrs.get("requirements", {})),
                )
                host_deps = set(as_iterable(reqs.get("host", set())))
                run_deps = set(as_iterable(reqs.get("run", set())))
                deps = host_deps.union(run_deps)

                # We are including the compiler stubs here so that
                # excluded_dependencies work correctly.
                # Edges to these compiler stubs are removed afterwards
                build_deps = set(as_iterable(reqs.get("build", set())))
                for build_dep in build_deps:
                    if build_dep.endswith("_stub"):
                        deps.add(build_dep)
                for dep in get_deps_from_outputs_lut(deps, graph.graph["outputs_lut"]):
                    graph2.add_edge(dep, node)

        super().__init__(
            graph=graph2,
            pr_limit=pr_limit,
            check_solvable=False,
            piggy_back_migrations=piggy_back_migrations,
        )

        assert (
            not self.check_solvable
        ), "We don't want to check solvability for arm osx!"

        self.name = name

        # Excluded dependencies need to be removed before no target_packages are
        # filtered out so that if a target_package is excluded, its dependencies
        # are not added to the graph
        for excluded_dep in self.excluded_dependencies:
            self.graph.remove_nodes_from(nx.descendants(self.graph, excluded_dep))

        # We are constraining the scope of this migrator
        with indir("../conda-forge-pinning-feedstock/recipe/migrations"), open(
            "osx_arm64.txt",
        ) as f:
            self.target_packages = set(f.read().split())

        # filter the graph down to the target packages
        if self.target_packages:
            self.target_packages.add("python")  # hack that is ~harmless?
            packages = self.target_packages.copy()
            for target in self.target_packages:
                if target in self.graph.nodes:
                    packages.update(nx.ancestors(self.graph, target))
            self.graph.remove_nodes_from([n for n in self.graph if n not in packages])

        # filter out stub packages and ignored packages
        for node, attrs in list(self.graph.nodes("payload")):
            if (
                not attrs
                or node.endswith("_stub")
                or (node.startswith("m2-"))
                or (node.startswith("m2w64-"))
                or (node in self.ignored_packages)
                or all_noarch(attrs)
            ):
                pluck(self.graph, node)

        self.graph.remove_edges_from(nx.selfloop_edges(self.graph))

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        if super().filter(attrs):
            return True
        muid = frozen_to_json_friendly(self.migrator_uid(attrs))
        for arch in self.arches:
            configured_arch = (
                attrs.get("conda-forge.yml", {}).get("provider", {}).get(arch)
            )
            if configured_arch:
                return muid in _sanitized_muids(attrs.get("PRed", []))
        else:
            return False

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        with indir(recipe_dir + "/.."):
            self.set_build_number("recipe/meta.yaml")
            with open("conda-forge.yml") as f:
                y = yaml_safe_load(f)
            y.update(self.additional_keys)
            with open("conda-forge.yml", "w") as f:
                safe_dump(y, f)

        return super().migrate(recipe_dir, attrs, **kwargs)

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return "ARM OSX Migrator"

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            dedent(
                """\
        This feedstock is being rebuilt as part of the ARM OSX migration.

        **Feel free to merge the PR if CI is all green, but please don't close it
        without reaching out the the ARM OSX team first at @conda-forge/help-osx-arm64.**
        """,  # noqa
            ),
        )
        return body

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return super().remote_branch(feedstock_ctx) + "_arm_osx"
