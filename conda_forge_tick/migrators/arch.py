from textwrap import dedent
import typing
from typing import Optional, Set, List, Any

import networkx as nx
from ruamel.yaml import safe_load, safe_dump

from conda_forge_tick.contexts import FeedstockContext
from conda_forge_tick.migrators.core import _no_pr_pred
from conda_forge_tick.migrators.disabled.legacy import Rebuild
from conda_forge_tick.utils import frozen_to_json_friendly
from ..xonsh_utils import indir


if typing.TYPE_CHECKING:
    from ..migrators_types import *


class ArchRebuild(Rebuild):
    """
    A Migrator that add aarch64 and ppc64le builds to feedstocks
    """

    migrator_version = 1
    rerender = True
    # We purposefully don't want to bump build number for this migrator
    bump_number = 0
    # We are constraining the scope of this migrator
    target_packages = {
        "ncurses",
        "conda-build",
        "conda-smithy",
        "conda-forge-ci-setup",
        "conda-package-handling",
        "numpy",
        "opencv",
        "ipython",
        "pandas",
        "tornado",
        "matplotlib",
        "dask",
        "distributed",
        "zeromq",
        "notebook",
        "scipy",
        "libarchive",
        "zstd",
        "krb5",
        "scikit-learn",
        "scikit-image" "su-exec",
        "flask",
        "sqlalchemy",
        "psycopg2",
        "tini",
        "clangdev",
        "pyarrow",
        "numba",
        "r-base",
        "protobuf",
        "cvxpy",
        "gevent",
        "gunicorn",
        "sympy",
        "tqdm",
        "spacy",
        "lime",
        "shap",
        "tesseract",
        # mpi variants
        "openmpi",
        "mpich",
        "poetry",
        "flit",
        "constructor",
        # py27 things
        "typing",
        "enum34",
        "functools32",
        "jsoncpp",
        "bcrypt",
        "root",
        "pyopencl",
        "pocl",
        "oclgrind",
        "sage",
        "boost-histogram",
        "uproot",
        "iminuit",
        "geant4",
        "pythia8",
        "hepmc3",
        "root_pandas",
        "lhcbdirac",
        "pytest-benchmark",
    }
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
        top_level: Set["PackageName"] = None,
        cycles: Optional[List["PackageName"]] = None,
    ):
        super().__init__(
            graph=graph,
            name=name,
            pr_limit=pr_limit,
            top_level=top_level,
            cycles=cycles,
        )
        # filter the graph down to the target packages
        if self.target_packages:
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
            ):
                self.graph.remove_node(node)

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        if super().filter(attrs):
            return True
        muid = frozen_to_json_friendly(self.migrator_uid(attrs))
        for arch in self.arches:
            configured_arch = (
                attrs.get("conda-forge.yml", {}).get("provider", {}).get(arch)
            )
            if configured_arch:
                return muid in _no_pr_pred(attrs.get("PRed", []))
        else:
            return False

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        with indir(recipe_dir + "/.."):
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
        body = dedent(
            """\
        This feedstock is being rebuilt as part of the aarch64/ppc64le migration.

        **Feel free to merge the PR if CI is all green, but please don't close it
        without reaching out the the ARM migrators first at @conda-forge/arm-arch.**
        """
        )
        return body

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return super().remote_branch(feedstock_ctx) + "_arch"