import copy
import logging
import tempfile
from pathlib import Path
from unittest.mock import create_autospec

from conda_forge_tick.auto_tick import _prepare_feedstock_repository
from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.git_utils import (
    DryRunBackend,
    GitPlatformBackend,
    RepositoryNotFoundError,
)
from conda_forge_tick.lazy_json_backends import LazyJson
from conda_forge_tick.migrators_types import AttrsTypedDict

demo_attrs = AttrsTypedDict(
    {"conda-forge.yml": {"provider": {"default_branch": "main"}}}
)


def test_prepare_feedstock_repository_success():
    backend = create_autospec(GitPlatformBackend)

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        cloned_context = ClonedFeedstockContext(
            feedstock_name="pytest",
            attrs=demo_attrs,
            _default_branch="main",
            local_clone_dir=tmpdir,
        )

        assert (
            _prepare_feedstock_repository(
                backend, cloned_context, "new_branch", "base_branch"
            )
            is True
        )

        backend.fork.assert_called_once_with("conda-forge", "pytest-feedstock")

        backend.clone_fork_and_branch.assert_called_once_with(
            upstream_owner="conda-forge",
            repo_name="pytest-feedstock",
            target_dir=tmpdir,
            new_branch="new_branch",
            base_branch="base_branch",
        )


def test_prepare_feedstock_repository_repository_not_found(caplog):
    backend = create_autospec(GitPlatformBackend)

    caplog.set_level(logging.WARNING)

    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)

        demo_attrs_copy = copy.deepcopy(demo_attrs)

        attrs = LazyJson(str(tmpdir / "test-attrs-1337.json"))
        pr_info = LazyJson(str(tmpdir / "test-pr-info-1337.json"))

        with attrs:
            for key, value in demo_attrs_copy.items():
                attrs[key] = value
            attrs["pr_info"] = pr_info

        cloned_context = ClonedFeedstockContext(
            feedstock_name="pytest",
            attrs=attrs,  # type: ignore
            _default_branch="main",
            local_clone_dir=tmpdir,
        )

        backend.fork.side_effect = RepositoryNotFoundError(
            "Repository not found - MAGIC WORDS"
        )

        assert (
            _prepare_feedstock_repository(
                backend, cloned_context, "new_branch", "base_branch"
            )
            is False
        )

        backend.fork.assert_called_once_with("conda-forge", "pytest-feedstock")

        backend.clone_fork_and_branch.assert_not_called()

        assert "Not Found" in caplog.text
        assert "pytest: Git repository not found." in attrs["pr_info"]["bad"]


def test_prepare_feedstock_repository_complete_dry_run():
    """
    This test really clones the repository using the DryRunBackend.
    """

    backend = DryRunBackend()

    context = FeedstockContext(
        feedstock_name="pytest",
        attrs=demo_attrs,
    )

    with context.reserve_clone_directory() as cloned_context:
        assert (
            _prepare_feedstock_repository(backend, cloned_context, "new_branch", "main")
            is True
        )

        assert cloned_context.local_clone_dir.joinpath("conda-forge.yml").exists()

        # new_branch should be checked out
        assert (
            "new_branch"
            in backend.cli._run_git_command(
                ["status"], cloned_context.local_clone_dir
            ).stdout
        )
