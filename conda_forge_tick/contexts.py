import os
import typing
from dataclasses import dataclass

from networkx import DiGraph

from conda_forge_tick.lazy_json_backends import load

if typing.TYPE_CHECKING:
    from conda_forge_tick.migrators_types import AttrsTypedDict


if os.path.exists("all_feedstocks.json"):
    with open("all_feedstocks.json") as f:
        DEFAULT_BRANCHES = load(f).get("default_branches", {})
else:
    DEFAULT_BRANCHES = {}


@dataclass
class MigratorSessionContext:
    """Singleton session context. There should generally only be one of these"""

    graph: DiGraph = None
    smithy_version: str = ""
    pinning_version: str = ""
    dry_run: bool = True


@dataclass
class FeedstockContext:
    package_name: str
    feedstock_name: str
    attrs: "AttrsTypedDict"
    _default_branch: str = None

    @property
    def default_branch(self):
        if self._default_branch is None:
            return DEFAULT_BRANCHES.get(f"{self.feedstock_name}", "main")
        else:
            return self._default_branch

    @default_branch.setter
    def default_branch(self, v):
        self._default_branch = v
