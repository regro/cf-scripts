import os
import typing
from textwrap import dedent
from typing import Any, Optional, Sequence

import networkx as nx

from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.make_graph import (
    get_deps_from_outputs_lut,
    make_outputs_lut_from_graph,
)
from conda_forge_tick.migrators.core import GraphMigrator, _sanitized_muids
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import (
    as_iterable,
    frozen_to_json_friendly,
    pluck,
    yaml_safe_dump,
    yaml_safe_load,
)

from .migration_yaml import all_noarch

if typing.TYPE_CHECKING:
    from conda_forge_tick.migrators_types import AttrsTypedDict, MigrationUidTypedDict

from .core import MiniMigrator


def _filter_excluded_deps(graph, excluded_dependencies):
    """filter out excluded dependencies from the graph

    This function removes any node that descends from an excluded dependency
    in addition to removing the excluded dependency itself.

    **operates in place**
    """
    nodes_to_remove = set(excluded_dependencies)
    for excluded_dep in excluded_dependencies:
        nodes_to_remove |= set(nx.descendants(graph, excluded_dep))
    for node in nodes_to_remove:
        pluck(graph, node)
    # post-plucking cleanup
    graph.remove_edges_from(nx.selfloop_edges(graph))


def _cut_to_target_packages(graph, target_packages):
    """cut the graph to only the target packages

    **operates in place**
    """
    packages = target_packages.copy()
    for target in target_packages:
        if target in graph.nodes:
            packages.update(nx.ancestors(graph, target))
    for node in list(graph.nodes.keys()):
        if node not in packages:
            pluck(graph, node)
    # post-plucking cleanup
    graph.remove_edges_from(nx.selfloop_edges(graph))


def _filter_stubby_and_ignored_nodes(graph, ignored_packages):
    """remove any stub packages and ignored packages from the graph

    **operates in place**
    """
    # filter out stub packages and ignored packages
    for node, attrs in list(graph.nodes("payload")):
        if (
            (not attrs)
            or node.endswith("_stub")
            or node.startswith("m2-")
            or node.startswith("m2w64-")
            or node.startswith("__")
            or (node in ignored_packages)
            or all_noarch(attrs)
        ):
            pluck(graph, node)
    # post-plucking cleanup
    graph.remove_edges_from(nx.selfloop_edges(graph))


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
        target_packages: Optional[Sequence[str]] = None,
        effective_graph: nx.DiGraph = None,
        _do_init: bool = True,
    ):
        if _do_init:
            if target_packages is None:
                # We are constraining the scope of this migrator
                with open(
                    os.path.join(
                        os.environ["CONDA_PREFIX"],
                        "share",
                        "conda-forge",
                        "migrations",
                        "arch_rebuild.txt",
                    )
                ) as f:
                    target_packages = set(f.read().split())

            if "outputs_lut" not in graph.graph:
                graph.graph["outputs_lut"] = make_outputs_lut_from_graph(graph)

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
                    for dep in get_deps_from_outputs_lut(
                        deps, graph.graph["outputs_lut"]
                    ):
                        graph2.add_edge(dep, node)
                pass

            graph = graph2
            target_packages = set(target_packages)
            if target_packages:
                target_packages.add("python")  # hack that is ~harmless?
                _cut_to_target_packages(graph, target_packages)

            # filter out stub packages and ignored packages
            _filter_stubby_and_ignored_nodes(graph, self.ignored_packages)

        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "graph": graph,
                "name": name,
                "pr_limit": pr_limit,
                "piggy_back_migrations": piggy_back_migrations,
                "target_packages": target_packages,
                "effective_graph": effective_graph,
                "_do_init": False,
            }

        super().__init__(
            graph=graph,
            pr_limit=pr_limit,
            check_solvable=False,
            piggy_back_migrations=piggy_back_migrations,
            effective_graph=effective_graph,
        )

        assert not self.check_solvable, "We don't want to check solvability for aarch!"
        self.target_packages = target_packages
        self.name = name

        if _do_init:
            self._reset_effective_graph()

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        if super().filter(attrs):
            return True
        muid = frozen_to_json_friendly(self.migrator_uid(attrs))
        for arch in self.arches:
            configured_arch = (
                attrs.get("conda-forge.yml", {}).get("provider", {}).get(arch)
            )
            if configured_arch:
                return muid in _sanitized_muids(
                    attrs.get("pr_info", {}).get("PRed", []),
                )
        else:
            return False

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        with pushd(recipe_dir + "/.."):
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

    def pr_body(self, feedstock_ctx: ClonedFeedstockContext) -> str:
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
        "test": "native_and_emulated",
    }

    def __init__(
        self,
        graph: nx.DiGraph = None,
        name: Optional[str] = None,
        pr_limit: int = 0,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
        target_packages: Optional[Sequence[str]] = None,
        effective_graph: nx.DiGraph = None,
        _do_init: bool = True,
    ):
        if _do_init:
            if target_packages is None:
                # We are constraining the scope of this migrator
                with open(
                    os.path.join(
                        os.environ["CONDA_PREFIX"],
                        "share",
                        "conda-forge",
                        "migrations",
                        "osx_arm64.txt",
                    )
                ) as f:
                    target_packages = set(f.read().split())

            if "outputs_lut" not in graph.graph:
                graph.graph["outputs_lut"] = make_outputs_lut_from_graph(graph)

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
                    for dep in get_deps_from_outputs_lut(
                        deps, graph.graph["outputs_lut"]
                    ):
                        graph2.add_edge(dep, node)

            graph = graph2

            # Excluded dependencies need to be removed before non target_packages are
            # filtered out so that if a target_package is excluded, its dependencies
            # are not added to the graph
            _filter_excluded_deps(graph, self.excluded_dependencies)

            target_packages = set(target_packages)

            # filter the graph down to the target packages
            if target_packages:
                target_packages.add("python")  # hack that is ~harmless?
                _cut_to_target_packages(graph, target_packages)

            # filter out stub packages and ignored packages
            _filter_stubby_and_ignored_nodes(graph, self.ignored_packages)

        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "graph": graph,
                "name": name,
                "pr_limit": pr_limit,
                "piggy_back_migrations": piggy_back_migrations,
                "target_packages": target_packages,
                "effective_graph": effective_graph,
                "_do_init": False,
            }

        super().__init__(
            graph=graph,
            pr_limit=pr_limit,
            check_solvable=False,
            piggy_back_migrations=piggy_back_migrations,
            effective_graph=effective_graph,
        )

        assert (
            not self.check_solvable
        ), "We don't want to check solvability for arm osx!"
        self.target_packages = target_packages
        self.name = name

        if _do_init:
            self._reset_effective_graph()

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        if super().filter(attrs):
            return True
        muid = frozen_to_json_friendly(self.migrator_uid(attrs))
        for arch in self.arches:
            configured_arch = (
                attrs.get("conda-forge.yml", {}).get("provider", {}).get(arch)
            )
            if configured_arch:
                return muid in _sanitized_muids(
                    attrs.get("pr_info", {}).get("PRed", []),
                )
        else:
            return False

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        with pushd(recipe_dir + "/.."):
            self.set_build_number("recipe/meta.yaml")
            with open("conda-forge.yml") as f:
                y = yaml_safe_load(f)
            # we should do this recursively but the cf yaml is usually
            # one key deep so this is fine
            for k, v in self.additional_keys.items():
                if isinstance(v, dict):
                    if k not in y:
                        y[k] = {}
                    for _k, _v in v.items():
                        y[k][_k] = _v
                else:
                    y[k] = v
            with open("conda-forge.yml", "w") as f:
                yaml_safe_dump(y, f)

        return super().migrate(recipe_dir, attrs, **kwargs)

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return "ARM OSX Migrator"

    def pr_body(self, feedstock_ctx: ClonedFeedstockContext) -> str:
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
