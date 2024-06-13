import os
import typing
from dataclasses import dataclass
from pathlib import Path

from networkx import DiGraph

from conda_forge_tick.lazy_json_backends import load
from conda_forge_tick.utils import get_keys_default

if typing.TYPE_CHECKING:
    from conda_forge_tick.migrators_types import AttrsTypedDict


GIT_CLONE_DIR = Path("feedstocks").resolve()


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

    @property
    def git_repo_owner(self) -> str:
        return "conda-forge"

    @property
    def git_repo_name(self) -> str:
        return f"{self.feedstock_name}-feedstock"

    @property
    def git_href(self) -> str:
        """
        A link to the feedstocks GitHub repository.
        """
        return f"https://github.com/{self.git_repo_owner}/{self.git_repo_name}"

    @property
    def local_clone_dir(self) -> Path:
        """
        The local path to the feedstock repository.
        """
        return GIT_CLONE_DIR / self.git_repo_name

    @property
    def automerge(self) -> bool | str:
        """
        Get the automerge setting of the feedstock.

        Note: A better solution to implement this is to use the NodeAttributes Pydantic
        model for the attrs field. This will be done in the future.
        """
        return get_keys_default(
            self.attrs,
            ["conda-forge.yml", "bot", "automerge"],
            {},
            False,
        )

    @property
    def check_solvable(self) -> bool:
        """
        Get the check_solvable setting of the feedstock.

        Note: A better solution to implement this is to use the NodeAttributes Pydantic
        model for the attrs field. This will be done in the future.
        """
        return get_keys_default(
            self.attrs,
            ["conda-forge.yml", "bot", "check_solvable"],
            {},
            False,
        )
