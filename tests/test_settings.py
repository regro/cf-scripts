import os

import pytest
from pydantic import ValidationError

from conda_forge_tick.settings import (
    ENV_CONDA_FORGE_ORG,
    BotSettings,
    settings,
    use_settings,
)


class TestBotSettings:
    def test_parse(self, temporary_environment):
        os.environ["CF_TICK_CONDA_FORGE_ORG"] = "myorg"
        os.environ["CF_TICK_GRAPH_GITHUB_BACKEND_REPO"] = "graph-owner/graph-repo"
        os.environ["CF_TICK_GRAPH_REPO_DEFAULT_BRANCH"] = "mybranch"
        os.environ["RUNNER_DEBUG"] = "1"
        os.environ["CF_TICK_FRAC_UPDATE_UPSTREAM_VERSIONS"] = "0.5"
        os.environ["CF_TICK_FRAC_MAKE_GRAPH"] = "0.7"

        bot_settings = BotSettings()

        assert bot_settings.conda_forge_org == "myorg"
        assert bot_settings.graph_github_backend_repo == "graph-owner/graph-repo"
        assert bot_settings.graph_repo_default_branch == "mybranch"
        assert (
            bot_settings.graph_github_backend_raw_base_url
            == "https://github.com/graph-owner/graph-repo/raw/mybranch/"
        )
        assert bot_settings.github_runner_debug is True
        assert bot_settings.frac_update_upstream_versions == 0.5
        assert bot_settings.frac_make_graph == 0.7

    def test_defaults(self, temporary_environment):
        os.environ.clear()

        bot_settings = BotSettings()

        assert bot_settings.conda_forge_org == "conda-forge"
        assert bot_settings.graph_github_backend_repo == "regro/cf-graph-countyfair"
        assert bot_settings.graph_repo_default_branch == "master"
        assert bot_settings.github_runner_debug is False
        assert 0 <= bot_settings.frac_update_upstream_versions <= 1
        assert 0 <= bot_settings.frac_make_graph <= 1

    def test_env_conda_forge_org(self, temporary_environment):
        os.environ.clear()

        os.environ[ENV_CONDA_FORGE_ORG] = "myorg"

        bot_settings = BotSettings()

        assert bot_settings.conda_forge_org == "myorg"

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

    @pytest.mark.parametrize("value", [-0.1, 1.1])
    @pytest.mark.parametrize(
        "attribute", ["FRAC_UPDATE_UPSTREAM_VERSIONS", "FRAC_MAKE_GRAPH"]
    )
    def test_reject_invalid_fraction(
        self, attribute: str, value: float, temporary_environment
    ):
        os.environ.clear()

        os.environ[f"CF_TICK_{attribute}"] = str(value)

        with pytest.raises(ValidationError, match="Input should be (greater|less)"):
            BotSettings()

    @pytest.mark.parametrize("value", [0.0, 1.0])
    @pytest.mark.parametrize(
        "attribute", ["FRAC_UPDATE_UPSTREAM_VERSIONS", "FRAC_MAKE_GRAPH"]
    )
    def test_accept_valid_fraction(
        self, attribute: str, value: float, temporary_environment
    ):
        os.environ.clear()

        os.environ[f"CF_TICK_{attribute}"] = str(value)

        bot_settings = BotSettings()

        assert getattr(bot_settings, attribute.lower()) == value


def test_use_settings(temporary_environment):
    os.environ.clear()
    bot_settings = settings()
    bot_settings.github_runner_debug = True

    with use_settings(bot_settings):
        ret_settings = settings()
        assert ret_settings.github_runner_debug is True

        # there should be no side effects
        bot_settings.github_runner_debug = False
        ret_settings.github_runner_debug = False

        side_effect_check_settings = settings()
        assert side_effect_check_settings.github_runner_debug is True

    # the settings should be restored
    assert settings().github_runner_debug is False
