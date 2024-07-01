from __future__ import annotations

import os
import tempfile
import typing
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from networkx import DiGraph

from conda_forge_tick.lazy_json_backends import load
from conda_forge_tick.utils import get_keys_default

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


@dataclass(frozen=True)
class FeedstockContext:
    feedstock_name: str
    attrs: AttrsTypedDict
    _default_branch: str = None

    @property
    def default_branch(self):
        if self._default_branch is None:
            return DEFAULT_BRANCHES.get(f"{self.feedstock_name}", "main")
        else:
            return self._default_branch

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

    @contextmanager
    def reserve_clone_directory(self) -> Iterator[ClonedFeedstockContext]:
        """
        Reserve a temporary directory for the feedstock repository that will be available within the context manager.
        The returned context object will contain the path to the feedstock repository in local_clone_dir.
        After the context manager exits, the temporary directory will be deleted.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            local_clone_dir = Path(tmpdir) / self.git_repo_name
            local_clone_dir.mkdir()
            yield ClonedFeedstockContext(
                **self.__dict__,
                local_clone_dir=local_clone_dir,
            )


@dataclass(frozen=True, kw_only=True)
class ClonedFeedstockContext(FeedstockContext):
    """
    A FeedstockContext object that has reserved a temporary directory for the feedstock repository.
    """

    # Implementation Note: Keep this class frozen or there will be consistency issues if someone modifies
    # a ClonedFeedstockContext object in place - it will not be reflected in the original FeedstockContext object.
    local_clone_dir: Path

    @contextmanager
    def reserve_clone_directory(self) -> Iterator[ClonedFeedstockContext]:
        """
        This method is a no-op for ClonedFeedstockContext objects because the directory has already been reserved.
        """
        yield self

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
