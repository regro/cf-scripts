import os

import pytest
from pydantic import ValidationError

from conda_forge_tick.settings import ENV_CONDA_FORGE_ORG, BotSettings


class TestBotSettings:
    def test_parse(self, temporary_environment):
        os.environ["CF_TICK_CONDA_FORGE_ORG"] = "myorg"
        os.environ["CF_TICK_GRAPH_GITHUB_BACKEND_REPO"] = "graph-owner/graph-repo"
        os.environ["CF_TICK_GRAPH_REPO_DEFAULT_BRANCH"] = "mybranch"

        settings = BotSettings()

        assert settings.conda_forge_org == "myorg"
        assert settings.graph_github_backend_repo == "graph-owner/graph-repo"
        assert settings.graph_repo_default_branch == "mybranch"
        assert (
            settings.graph_github_backend_raw_base_url
            == "https://github.com/graph-owner/graph-repo/raw/mybranch"
        )

    def test_defaults(self, temporary_environment):
        os.environ.clear()

        settings = BotSettings()

        assert settings.conda_forge_org == "conda-forge"
        assert settings.graph_github_backend_repo == "regro/cf-graph-countyfair"
        assert settings.graph_repo_default_branch == "master"

    def test_env_conda_forge_org(self, temporary_environment):
        os.environ.clear()

        os.environ[ENV_CONDA_FORGE_ORG] = "myorg"

        settings = BotSettings()

        assert settings.conda_forge_org == "myorg"

    def test_reject_invalid_conda_forge_org(self, temporary_environment):
        os.environ.clear()

        os.environ["CF_TICK_CONDA_FORGE_ORG"] = "invalid org"

        with pytest.raises(ValidationError, match="should match pattern"):
            BotSettings()

    def test_reject_invalid_repo_pattern(self, temporary_environment):
        os.environ.clear()

        os.environ["CF_TICK_GRAPH_GITHUB_BACKEND_REPO"] = "no-owner-repo"

        with pytest.raises(ValidationError, match="should match pattern"):
            BotSettings()
