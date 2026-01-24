import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from github import Auth, Github, PullRequest
from ruamel import yaml

from conda_forge_tick.git_utils import GitCli
from conda_forge_tick.utils import (
    run_command_hiding_token,
)

from ._definitions import AbstractIntegrationTestHelper, GitHubAccount
from ._shared import (
    FEEDSTOCK_SUFFIX,
    get_github_token,
)

LOGGER = logging.getLogger(__name__)


class IntegrationTestHelper(AbstractIntegrationTestHelper):
    def overwrite_feedstock_contents(
        self, feedstock_name: str, source_dir: Path, branch: str = "main"
    ):
        self.overwrite_github_repository(
            GitHubAccount.CONDA_FORGE_ORG,
            feedstock_name + FEEDSTOCK_SUFFIX,
            source_dir,
            branch,
        )

    def overwrite_github_repository(
        self,
        owner_account: GitHubAccount,
        repo_name: str,
        source_dir: Path,
        branch: str = "main",
    ):
        # We execute all git operations in a separate temporary directory to avoid side effects.
        with TemporaryDirectory(repo_name) as tmpdir_str:
            tmpdir = Path(tmpdir_str)
            self._overwrite_github_repository_with_tmpdir(
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
        """See `overwrite_github_repository`."""
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
            "Repository contents of %s have been overwritten successfully.", repo_name
        )

    @staticmethod
    def _get_matching_pr(feedstock: str, pr_title_contains: str) -> PullRequest:
        gh = Github(auth=Auth.Token(get_github_token(GitHubAccount.CONDA_FORGE_ORG)))

        full_feedstock_name = feedstock + FEEDSTOCK_SUFFIX
        repo = gh.get_organization(GitHubAccount.CONDA_FORGE_ORG).get_repo(
            full_feedstock_name
        )
        matching_prs = [
            pr for pr in repo.get_pulls(state="open") if pr_title_contains in pr.title
        ]

        assert len(matching_prs) == 1, (
            f"Found {len(matching_prs)} matching version PRs, but exactly 1 must be present."
        )

        return matching_prs[0]

    def _get_matching_version_pr(
        self,
        feedstock: str,
        new_version: str,
    ) -> PullRequest:
        return self._get_matching_pr(
            feedstock=feedstock,
            pr_title_contains=f"v{new_version}",
        )

    def _assert_version_pr_meta(self, feedstock: str, pr: PullRequest):
        full_feedstock_name = feedstock + FEEDSTOCK_SUFFIX
        assert pr.head.repo.owner.login == GitHubAccount.BOT_USER
        assert pr.head.repo.name == full_feedstock_name

    def _assert_version_pr_content_v0(
        self,
        feedstock: str,
        pr: PullRequest,
        new_version: str,
        new_hash: str,
        old_version: str,
        old_hash: str,
    ):
        cli = GitCli()

        full_feedstock_name = feedstock + FEEDSTOCK_SUFFIX

        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / full_feedstock_name
            cli.clone_repo(pr.head.repo.clone_url, target_dir)
            cli.checkout_branch(target_dir, pr.head.ref)

            with open(target_dir / "recipe" / "meta.yaml") as f:
                meta = f.read()

        assert f'{{% set version = "{new_version}" %}}' in meta
        assert f"sha256: {new_hash}" in meta
        assert old_version not in meta
        assert old_hash not in meta

    def _get_pr_content_recipe_v1(
        self,
        pr: PullRequest,
    ) -> dict[str, Any]:
        cli = GitCli()
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir)
            cli.clone_repo(pr.head.repo.clone_url, target_dir)
            cli.checkout_branch(target_dir, pr.head.ref)
            with open(target_dir / "recipe" / "recipe.yaml") as f:
                yaml_ = yaml.YAML(typ="safe", pure=True)
                return yaml_.load(f)

    def _assert_version_pr_content_v1(
        self,
        pr: PullRequest,
        new_version: str,
        new_hash: str,
        old_version: str,
        old_hash: str,
    ):
        recipe = self._get_pr_content_recipe_v1(pr)
        yaml_ = yaml.YAML(typ="full", pure=True)
        sio = io.StringIO()
        yaml_.dump(recipe, stream=sio)
        recipe_raw = sio.getvalue()
        assert recipe["context"]["version"] == new_version
        assert recipe["source"]["sha256"] == new_hash
        assert old_version not in recipe_raw
        assert old_hash not in recipe_raw

    def assert_version_pr_present_v0(
        self,
        feedstock: str,
        new_version: str,
        new_hash: str,
        old_version: str,
        old_hash: str,
    ):
        pr = self._get_matching_version_pr(feedstock=feedstock, new_version=new_version)
        self._assert_version_pr_meta(feedstock=feedstock, pr=pr)
        self._assert_version_pr_content_v0(
            feedstock=feedstock,
            pr=pr,
            new_version=new_version,
            new_hash=new_hash,
            old_version=old_version,
            old_hash=old_hash,
        )
        LOGGER.info(
            "Version PR for %s v%s validated successfully.",
            feedstock,
            new_version,
        )

    def assert_version_pr_present_v1(
        self,
        feedstock: str,
        new_version: str,
        new_hash: str,
        old_version: str,
        old_hash: str,
    ):
        pr = self._get_matching_version_pr(feedstock=feedstock, new_version=new_version)
        self._assert_version_pr_meta(feedstock=feedstock, pr=pr)
        self._assert_version_pr_content_v1(
            pr=pr,
            new_version=new_version,
            new_hash=new_hash,
            old_version=old_version,
            old_hash=old_hash,
        )
        LOGGER.info(
            "Version PR for %s v%s validated successfully.",
            feedstock,
            new_version,
        )

    def assert_bot_pr_contents_v1(
        self,
        feedstock: str,
        title_contains: str,
        included: list[str],
        not_included: list[str],
    ):
        pr = self._get_matching_pr(feedstock, title_contains)
        self._assert_version_pr_meta(feedstock, pr)

        recipe = self._get_pr_content_recipe_v1(pr)
        yaml_ = yaml.YAML(typ="full", pure=True)
        sio = io.StringIO()
        yaml_.dump(recipe, stream=sio)
        recipe_raw = sio.getvalue()
        for included_str in included:
            assert included_str in recipe_raw, f"{included_str} not in recipe_raw"

        for not_included_str in not_included:
            assert not_included_str not in recipe_raw, (
                f"{not_included_str} in recipe_raw"
            )

        LOGGER.info(
            "Bot PR for %s ('%s') validated successfully.",
            feedstock,
            title_contains,
        )

    def assert_new_run_requirements_equal_v1(
        self,
        feedstock: str,
        new_version: str,
        run_requirements: list[str],
    ):
        pr = self._get_matching_version_pr(feedstock=feedstock, new_version=new_version)
        recipe = self._get_pr_content_recipe_v1(pr)
        assert recipe["requirements"]["run"] == run_requirements

    def assert_pr_title_starts_with(
        self,
        feedstock: str,
        pr_title_contains: str,
        expected_prefix: str,
    ):
        pr = self._get_matching_pr(feedstock, pr_title_contains)
        assert pr.title.startswith(expected_prefix), (
            f"PR title '{pr.title}' does not start with expected prefix '{expected_prefix}'"
        )
        LOGGER.info(
            "PR title for %s verified to start with '%s'.",
            feedstock,
            expected_prefix,
        )
