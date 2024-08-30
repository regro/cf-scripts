import logging
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from conda_forge_tick.utils import (
    print_subprocess_output_strip_token,
)
from tests_integration.shared import FEEDSTOCK_SUFFIX, GitHubAccount, get_github_token

LOGGER = logging.getLogger(__name__)


class IntegrationTestHelper:
    @classmethod
    def overwrite_feedstock_contents(cls, feedstock_name: str, source_dir: Path):
        """
        Overwrite the contents of the feedstock with the contents of the source directory.
        This prunes the entire git history.

        :param feedstock_name: The name of the feedstock repository, without the "-feedstock" suffix.
        :param source_dir: The directory containing the new contents of the feedstock.
        """
        # We execute all git operations in a separate temporary directory to avoid side effects.
        with TemporaryDirectory(feedstock_name) as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            cls._overwrite_feedstock_contents_with_tmpdir(
                feedstock_name, source_dir, tmpdir
            )

    @staticmethod
    def _overwrite_feedstock_contents_with_tmpdir(
        feedstock_name: str, source_dir: Path, tmpdir: Path
    ):
        """
        See `overwrite_feedstock_contents`.
        """
        tmp_feedstock_dir = tmpdir / f"{feedstock_name}{FEEDSTOCK_SUFFIX}"
        shutil.copytree(source_dir, tmp_feedstock_dir)

        # Remove the .git directory (if it exists)
        shutil.rmtree(tmp_feedstock_dir / ".git", ignore_errors=True)

        # Initialize a new git repository and commit everything
        subprocess.run(["git", "init"], cwd=tmp_feedstock_dir, check=True)
        subprocess.run(["git", "add", "--all"], cwd=tmp_feedstock_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Overwrite Feedstock Contents"],
            cwd=tmp_feedstock_dir,
            check=True,
        )

        # Push the new contents to the feedstock repository
        push_token = get_github_token(GitHubAccount.CONDA_FORGE_ORG)
        push_res = subprocess.run(
            [
                "git",
                "push",
                f"https://{push_token}@github.com/{GitHubAccount.CONDA_FORGE_ORG}/{feedstock_name}{FEEDSTOCK_SUFFIX}.git",
                "main",
                "--force",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=tmp_feedstock_dir,
            check=True,
        )

        print_subprocess_output_strip_token(push_res, token=push_token)

        LOGGER.info(
            f"Feedstock contents of {feedstock_name} have been overwritten successfully."
        )
