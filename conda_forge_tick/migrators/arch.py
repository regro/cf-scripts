import copy
import os
from textwrap import dedent
from typing import Any, Collection, Literal, Optional, Sequence

import networkx as nx

from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.make_graph import (
    get_deps_from_outputs_lut,
)
from conda_forge_tick.migrators.core import (
    GraphMigrator,
    MiniMigrator,
    cut_graph_to_target_packages,
    get_outputs_lut,
    load_target_packages,
)
from conda_forge_tick.migrators_types import AttrsTypedDict, MigrationUidTypedDict
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import (
    as_iterable,
    pluck,
    yaml_safe_dump,
    yaml_safe_load,
)

from .migration_yaml import all_noarch


def _filter_excluded_deps(graph, excluded_dependencies):
    """Filter out excluded dependencies from the graph.

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


def _filter_stubby_and_ignored_nodes(graph, ignored_packages):
    """Remove any stub packages and ignored packages from the graph.

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
    """A Migrator that adds aarch64 and ppc64le builds to feedstocks."""

    allowed_schema_versions = {0, 1}
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
        graph: nx.DiGraph | None = None,
        name: str = "aarch64 and ppc64le addition",
        pr_limit: int = 0,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
        target_packages: Optional[Collection[str]] = None,
        effective_graph: nx.DiGraph | None = None,
        total_graph: nx.DiGraph | None = None,
    ):
        if total_graph is not None:
            if target_packages is None:
                # We are constraining the scope of this migrator
                target_packages = load_target_packages("arch_rebuild.txt")

            outputs_lut = get_outputs_lut(total_graph, graph, effective_graph)

            # rebuild the graph to only use edges from the arm and power requirements
            graph2 = nx.create_empty_copy(total_graph)
            for node, attrs in total_graph.nodes(data="payload"):
                for plat_arch in self.arches:
                    deps = set().union(
                        *attrs.get(
                            f"{plat_arch}_requirements",
                            attrs.get("requirements", {}),
                        ).values()
                    )
                    for dep in get_deps_from_outputs_lut(deps, outputs_lut):  # type: ignore[arg-type]
                        graph2.add_edge(dep, node)
                pass

            total_graph = graph2
            target_packages = set(target_packages)
            if target_packages:
                target_packages.add("python")  # hack that is ~harmless?
                total_graph = cut_graph_to_target_packages(total_graph, target_packages)

            # filter out stub packages and ignored packages
            _filter_stubby_and_ignored_nodes(total_graph, self.ignored_packages)

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
                "total_graph": total_graph,
            }

        self.target_packages = target_packages

        super().__init__(
            graph=graph,
            pr_limit=pr_limit,
            check_solvable=False,
            piggy_back_migrations=piggy_back_migrations,
            effective_graph=effective_graph,
            total_graph=total_graph,
            name=name,
        )
        assert not self.check_solvable, "We don't want to check solvability for aarch!"

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> MigrationUidTypedDict | Literal[False]:
        with pushd(recipe_dir + "/.."):
            recipe_file = next(
                filter(os.path.exists, ("recipe/recipe.yaml", "recipe/meta.yaml"))
            )
            self.set_build_number(recipe_file)

            with open("conda-forge.yml") as f:
                y = yaml_safe_load(f)

            y_orig = copy.deepcopy(y)

            if "provider" not in y:
                y["provider"] = {}
            for k, v in self.arches.items():
                if k not in y["provider"]:
                    y["provider"][k] = v

            with open("conda-forge.yml", "w") as f:
                yaml_safe_dump(y, f)

        muid = super().migrate(recipe_dir, attrs, **kwargs)
        if muid is False:
            return False
        if y_orig == y:
            muid["already_done"] = True

        return muid

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        title = "Arch Migrator"
        branch = feedstock_ctx.attrs.get("branch", "main")
        if branch not in ["main", "master"]:
            return f"[{branch}] " + title
        else:
            return title

    def pr_body(
        self, feedstock_ctx: ClonedFeedstockContext, add_label_text: bool = False
    ) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            dedent(
                """\
        This feedstock is being rebuilt as part of the aarch64/ppc64le migration.

        **Feel free to merge the PR if CI is all green, but please don't close it
        without reaching out the the ARM migrators first at <code>@</code>conda-forge/arm-arch.**
        """,
            ),
        )
        return body

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return super().remote_branch(feedstock_ctx) + "_arch"


class _CrossCompileRebuild(GraphMigrator):
    """A Migrator that adds arch platform builds to feedstocks."""

    rerender = True
    # We purposefully don't want to bump build number for this migrator
    bump_number = 0

    ignored_packages: set[str] = set()
    excluded_dependencies: set[str] = set()

    @property
    def additional_keys(self):
        return {
            "build_platform": self.build_platform,  # type: ignore[attr-defined]
            "test": "native_and_emulated",
        }

    def __init__(
        self,
        graph: nx.DiGraph | None = None,
        pr_limit: int = 0,
        name: str = "",
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
        target_packages: Optional[Collection[str]] = None,
        effective_graph: nx.DiGraph | None = None,
        total_graph: nx.DiGraph | None = None,
    ):
        if total_graph is not None:
            if target_packages is None:
                # We are constraining the scope of this migrator
                target_packages = load_target_packages(self.pkg_list_filename)  # type: ignore[attr-defined]
            outputs_lut = get_outputs_lut(total_graph, graph, effective_graph)

            # rebuild the graph to only use edges from the arch requirements
            graph2 = nx.create_empty_copy(total_graph)
            for node, attrs in total_graph.nodes(data="payload"):
                for plat_arch, build_plat_arch in self.build_platform.items():  # type: ignore[attr-defined]
                    reqs = attrs.get(
                        f"{plat_arch}_requirements",
                        attrs.get(
                            f"{build_plat_arch}_requirements",
                            attrs.get("requirements", {}),
                        ),
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
                        deps,
                        outputs_lut,  # type: ignore[arg-type]
                    ):
                        graph2.add_edge(dep, node)

            total_graph = graph2

            # Excluded dependencies need to be removed before non target_packages are
            # filtered out so that if a target_package is excluded, its dependencies
            # are not added to the graph
            _filter_excluded_deps(total_graph, self.excluded_dependencies)

            target_packages = set(target_packages)

            # filter the graph down to the target packages
            if target_packages:
                target_packages.add("python")  # hack that is ~harmless?
                total_graph = cut_graph_to_target_packages(total_graph, target_packages)

            # filter out stub packages and ignored packages
            _filter_stubby_and_ignored_nodes(total_graph, self.ignored_packages)

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
                "total_graph": total_graph,
            }

        self.target_packages = target_packages

        super().__init__(
            graph=graph,
            pr_limit=pr_limit,
            check_solvable=False,
            piggy_back_migrations=piggy_back_migrations,
            effective_graph=effective_graph,
            total_graph=total_graph,
            name=name,
        )
        assert not self.check_solvable, "We don't want to check solvability!"

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> MigrationUidTypedDict | Literal[False]:
        with pushd(recipe_dir + "/.."):
            recipe_file = next(
                filter(os.path.exists, ("recipe/recipe.yaml", "recipe/meta.yaml"))
            )
            self.set_build_number(recipe_file)

            with open("conda-forge.yml") as f:
                y = yaml_safe_load(f)

            y_orig = copy.deepcopy(y)

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

        muid = super().migrate(recipe_dir, attrs, **kwargs)
        if muid is False:
            return muid
        if y_orig == y:
            muid["already_done"] = True

        return muid


class OSXArm(_CrossCompileRebuild):
    """A Migrator that adds osx-arm64 builds to feedstocks."""

    allowed_schema_versions = {0, 1}
    migrator_version = 1
    build_platform = {"osx_arm64": "osx_64"}
    pkg_list_filename = "osx_arm64.txt"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("name", "arm osx addition")
        super().__init__(*args, **kwargs)

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        title = "ARM OSX Migrator"
        branch = feedstock_ctx.attrs.get("branch", "main")
        if branch not in ["main", "master"]:
            return f"[{branch}] " + title
        else:
            return title

    def pr_body(
        self, feedstock_ctx: ClonedFeedstockContext, add_label_text: bool = True
    ) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            dedent(
                """\
        This feedstock is being rebuilt as part of the ARM OSX migration.

        **Feel free to merge the PR if CI is all green, but please don't close it
        without reaching out the the ARM OSX team first at <code>@</code>conda-forge/help-osx-arm64.**
        """,  # noqa
            ),
        )
        return body

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return super().remote_branch(feedstock_ctx) + "_arm_osx"


class WinArm64(_CrossCompileRebuild):
    """A Migrator that adds win-arm64 builds to feedstocks."""

    allowed_schema_versions = {0, 1}
    migrator_version = 1
    build_platform = {"win_arm64": "win_64"}
    pkg_list_filename = "win_arm64.txt"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("name", "support windows arm64 platform")
        super().__init__(*args, **kwargs)

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        title = "Support Windows ARM64 platform"
        branch = feedstock_ctx.attrs.get("branch", "main")
        if branch not in ["main", "master"]:
            return f"[{branch}] " + title
        else:
            return title

    def pr_body(
        self, feedstock_ctx: ClonedFeedstockContext, add_label_text: bool = True
    ) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            dedent(
                """\
        This feedstock is being rebuilt as part of the windows arm migration.

        **Feel free to merge the PR if CI is all green, but please don't close it
        without reaching out the the ARM Windows team first at <code>@</code>conda-forge/help-win-arm64.**
        """,
            ),
        )
        return body

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return super().remote_branch(feedstock_ctx) + "_arm64_win"
