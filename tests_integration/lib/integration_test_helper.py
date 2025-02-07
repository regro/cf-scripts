import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from tempfile import TemporaryDirectory

from github import Github

from conda_forge_tick.git_utils import GitCli
from conda_forge_tick.utils import (
    run_command_hiding_token,
)
from tests_integration.lib.shared import (
    FEEDSTOCK_SUFFIX,
    GitHubAccount,
    get_github_token,
)

LOGGER = logging.getLogger(__name__)


class IntegrationTestHelper:
    @classmethod
    def overwrite_feedstock_contents(
        cls, feedstock_name: str, source_dir: Path, branch: str = "main"
    ):
        """
        Overwrite the contents of the feedstock with the contents of the source directory.
        This prunes the entire git history.

        :param feedstock_name: The name of the feedstock repository, without the "-feedstock" suffix.
        :param source_dir: The directory containing the new contents of the feedstock.
        :param branch: The branch to overwrite.
        """
        cls.overwrite_github_repository(
            GitHubAccount.CONDA_FORGE_ORG,
            feedstock_name + FEEDSTOCK_SUFFIX,
            source_dir,
            branch,
        )

    @classmethod
    def overwrite_github_repository(
        cls,
        owner_account: GitHubAccount,
        repo_name: str,
        source_dir: Path,
        branch: str = "main",
    ):
        """
        Overwrite the contents of the repository with the contents of the source directory.
        This prunes the entire git history.

        :param owner_account: The owner of the repository.
        :param repo_name: The name of the repository.
        :param source_dir: The directory containing the new contents of the repository.
        :param branch: The branch to overwrite.
        """
        # We execute all git operations in a separate temporary directory to avoid side effects.
        with TemporaryDirectory(repo_name) as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            cls._overwrite_github_repository_with_tmpdir(
                owner_account, repo_name, source_dir, tmpdir, branch
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
        See `overwrite_github_repository`.
        """
        dest_dir = tmpdir / repo_name
        shutil.copytree(source_dir, dest_dir)

        # Remove the .git directory (if it exists)
        shutil.rmtree(dest_dir / ".git", ignore_errors=True)
        dest_dir.joinpath(".git").unlink(missing_ok=True)  # if it is a file

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

    @staticmethod
    def assert_version_pr_present(
        feedstock: str, new_version: str, new_hash: str, old_version: str, old_hash: str
    ):
        """
        Asserts that the bot has opened a version update PR.

        :param feedstock: The feedstock we expect the PR for, without the -feedstock suffix.
        :param new_version: The new version that is expected.
        :param new_hash: The new SHA-256 source artifact hash.
        :param old_version: The old version of the feedstock, to check that it no longer appears in the recipe.
        :param old_hash: The old SHA-256 source artifact hash, to check that it no longer appears in the recipe.

        :raises AssertionError: if the assertion fails
        """
        gh = Github(get_github_token(GitHubAccount.CONDA_FORGE_ORG))

        full_feedstock_name = feedstock + FEEDSTOCK_SUFFIX
        repo = gh.get_organization(GitHubAccount.CONDA_FORGE_ORG).get_repo(
            full_feedstock_name
        )
        matching_prs = [
            pr for pr in repo.get_pulls(state="open") if f"v{new_version}" in pr.title
        ]

        assert len(matching_prs) == 1, (
            f"Found {len(matching_prs)} matching version PRs, but exactly 1 must be present."
        )

        matching_pr = matching_prs[0]

        assert matching_pr.head.repo.owner.login == GitHubAccount.BOT_USER
        assert matching_pr.head.repo.name == full_feedstock_name

        cli = GitCli()

        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / full_feedstock_name
            cli.clone_repo(matching_pr.head.repo.clone_url, target_dir)
            cli.checkout_branch(target_dir, matching_pr.head.ref)

            with open(target_dir / "recipe" / "meta.yaml") as f:
                meta = f.read()

        assert f'{{% set version = "{new_version}" %}}' in meta
        assert f"sha256: {new_hash}" in meta
        assert old_version not in meta
        assert old_hash not in meta

        LOGGER.info(
            f"Version PR for {feedstock} v{new_version} validated successfully."
        )
