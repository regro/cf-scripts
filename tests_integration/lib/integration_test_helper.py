import logging
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from conda_forge_tick.utils import (
    run_command_hiding_token,
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
        cls.overwrite_github_repository(
            GitHubAccount.CONDA_FORGE_ORG, feedstock_name + FEEDSTOCK_SUFFIX, source_dir
        )

    @classmethod
    def overwrite_github_repository(
        cls, owner_account: GitHubAccount, repo_name: str, source_dir: Path
    ):
        """
        Overwrite the contents of the repository with the contents of the source directory.
        This prunes the entire git history.

        :param owner_account: The owner of the repository.
        :param repo_name: The name of the repository.
        :param source_dir: The directory containing the new contents of the repository.
        """
        # We execute all git operations in a separate temporary directory to avoid side effects.
        with TemporaryDirectory(repo_name) as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            cls._overwrite_github_repository_with_tmpdir(
                owner_account, repo_name, source_dir, tmpdir, branch="master"
            )

    @staticmethod
    def _overwrite_github_repository_with_tmpdir(
        owner_account: GitHubAccount,
        repo_name: str,
        source_dir: Path,
        tmpdir: Path,
        branch: str = "main",
    ):
        """
        See `overwrite_feedstock_contents`.
        """
        dest_dir = tmpdir / repo_name
        shutil.copytree(source_dir, dest_dir)

        # Remove the .git directory (if it exists)
        shutil.rmtree(dest_dir / ".git", ignore_errors=True)

        # Initialize a new git repository and commit everything
        subprocess.run(
            ["git", "init", f"--initial-branch={branch}"], cwd=dest_dir, check=True
        )
        subprocess.run(["git", "add", "--all"], cwd=dest_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Overwrite Repository Contents"],
            cwd=dest_dir,
            check=True,
        )

        # Push the new contents to the repository
        push_token = get_github_token(owner_account)
        run_command_hiding_token(
            [
                "git",
                "push",
                f"https://{push_token}@github.com/{owner_account}/{repo_name}.git",
                branch,
                "--force",
            ],
            token=push_token,
            cwd=dest_dir,
            check=True,
        )

        LOGGER.info(
            f"Repository contents of {repo_name} have been overwritten successfully."
        )
