from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from networkx import DiGraph

from conda_forge_tick.lazy_json_backends import load
from conda_forge_tick.migrators_types import AttrsTypedDict
from conda_forge_tick.utils import get_keys_default

if os.path.exists("all_feedstocks.json"):
    with open("all_feedstocks.json") as f:
        DEFAULT_BRANCHES = load(f).get("default_branches", {})
else:
    DEFAULT_BRANCHES = {}


@dataclass
class MigratorSessionContext:
    """Singleton session context. There should generally only be one of these."""

    graph: DiGraph = None
    smithy_version: str = ""
    pinning_version: str = ""


@dataclass(frozen=True)
class FeedstockContext:
    feedstock_name: str
    attrs: AttrsTypedDict
    default_branch: str = ""
    """
    If not provided, this is set to a default branch read from all_feedstocks.json, or 'main'.
    """
    git_repo_owner: str = "conda-forge"
    """
    The owner of the upstream git repository.
    """

    def __post_init__(self):
        if not self.default_branch:
            object.__setattr__(
                self,
                "default_branch",
                DEFAULT_BRANCHES.get(self.feedstock_name, "main"),
            )

    @property
    def git_repo_name(self) -> str:
        return f"{self.feedstock_name}-feedstock"

    @property
    def git_http_ref(self) -> str:
        """A link to the feedstock's GitHub repository."""
        return f"https://github.com/{self.git_repo_owner}/{self.git_repo_name}"

    @property
    def automerge(self) -> bool | str:
        """
        Get the automerge setting of the feedstock.
        Note: A better solution to implement this is to use the NodeAttributes Pydantic
        model for the attrs field. This can be done in the future.
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
        model for the attrs field. This can be done in the future.
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

    Implementation Note: Keep this class frozen or there will be consistency issues if someone modifies
    a ClonedFeedstockContext object in place - it will not be reflected in the original FeedstockContext object.

    """

    local_clone_dir: Path
