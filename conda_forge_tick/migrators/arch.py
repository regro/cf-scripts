from textwrap import dedent
import typing
from typing import Optional, Any

import networkx as nx
from ruamel.yaml import safe_load, safe_dump

from conda_forge_tick.contexts import FeedstockContext
from conda_forge_tick.migrators.core import _sanitized_muids, GraphMigrator
from conda_forge_tick.utils import frozen_to_json_friendly, pluck
from ..xonsh_utils import indir


if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict, MigrationUidTypedDict


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
        self, graph: nx.DiGraph = None, name: Optional[str] = None, pr_limit: int = 0,
    ):
        # rebuild the graph to only use edges from the arm and power requirements
        graph2 = nx.create_empty_copy(graph)
        for node, attrs in graph.nodes(data='payload'):
            for plat_arch in self.arches:
                deps = set().union(*attrs.get(f"{plat_arch}_requirements", attrs.get('requirements', {})).values())
                for dep in deps:
                    graph2.add_edge(dep, node)

        super().__init__(graph=graph2, pr_limit=pr_limit, check_solvable=False)

        assert not self.check_solvable, "We don't want to check solvability for aarch!"
        # We are constraining the scope of this migrator
        with indir("../conda-forge-pinning-feedstock/recipe/migrations"), open(
            "arch_rebuild.txt", "r"
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
        for node in list(self.graph.nodes):
            if (
                node.endswith("_stub")
                or (node.startswith("m2-"))
                or (node.startswith("m2w64-"))
                or (node in self.ignored_packages)
                or (
                    self.graph.nodes[node]
                    .get("payload", {})
                    .get("meta_yaml", {})
                    .get("build", {})
                    .get("noarch")
                )
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
            with open("conda-forge.yml", "r") as f:
                y = safe_load(f)
            if "provider" not in y:
                y["provider"] = {}
            for k, v in self.arches.items():
                if k not in y["provider"]:
                    y["provider"][k] = v

            with open("conda-forge.yml", "w") as f:
                safe_dump(y, f)

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
        """
            )
        )
        return body

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return super().remote_branch(feedstock_ctx) + "_arch"
