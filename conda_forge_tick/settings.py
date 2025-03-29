from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENVIRONMENT_PREFIX = "CF_TICK_"
"""
All environment variables are expected to be prefixed with this.
"""

ENV_CONDA_FORGE_ORG = ENVIRONMENT_PREFIX + "CONDA_FORGE_ORG"
"""
The environment variable used to set the `conda_forge_org` setting.
Note: This must match the field name in the `BotSettings` class.
"""

Fraction = Annotated[float, Field(ge=0.0, le=1.0)]


class BotSettings(BaseSettings):
    """
    The global settings for the bot.

    To configure a settings value, set the corresponding environment variable with the prefix `CF_TICK_`.
    For example, to set the `graph_github_backend_repo` setting, set the environment variable
    `CF_TICK_GRAPH_GITHUB_BACKEND_REPO`.

    To access the current settings object, please use the `settings()` function.

    Note: There still exists a significant amount of settings that are not yet exposed here.
    All new settings should go here, and the other ones should eventually be migrated.
    """

    model_config = SettingsConfigDict(env_prefix=ENVIRONMENT_PREFIX)

    conda_forge_org: str = Field("conda-forge", pattern=r"^[\w\.-]+$")
    """
    The GitHub organization containing all feedstocks. Default: "conda-forge".
    If you change the field name, you must also update the `ENV_CONDA_FORGE_ORG` constant.
    """

    graph_github_backend_repo: str = Field(
        "regro/cf-graph-countyfair", pattern=r"^[\w\.-]+/[\w\.-]+$"
    )
    """
    The GitHub repository to deploy to. Default: "regro/cf-graph-countyfair".
    """

    graph_repo_default_branch: str = "master"
    """
    The default branch of the graph_github_backend_repo repository.
    """

    @property
    def graph_github_backend_raw_base_url(self) -> str:
        """
        The base URL for the GitHub raw view of the graph_github_backend_repo repository.
        Example: https://github.com/regro/cf-graph-countyfair/raw/master
        """
        return f"https://github.com/{self.graph_github_backend_repo}/raw/{self.graph_repo_default_branch}"

    github_runner_debug: bool = Field(False, alias="RUNNER_DEBUG")
    """
    Whether we are executing within a GitHub Actions run with debug logging enabled. Default: False.
    This is set automatically by GitHub Actions.
    https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/store-information-in-variables#default-environment-variables
    """

    frac_update_upstream_versions: Fraction = 0.1
    """
    The fraction of feedstocks (randomly selected) to update in the update-upstream-versions job.
    This is currently only respected when running concurrently (via process pool), not in sequential mode.
    Therefore, you don't need to set this when debugging locally.
    """

    frac_make_graph: Fraction = 0.1
    """
    The fraction of feedstocks (randomly selected) to update in the make-graph job.
    In tests or when debugging, you probably need to set this to 1.0 to update all feedstocks.
    """


_USE_SETTINGS_OVERRIDE: BotSettings | None = None
"""
If not None, the application should use this settings object instead of generating a new one.
"""


def settings() -> BotSettings:
    """
    Get the current settings object.
    """
    if _USE_SETTINGS_OVERRIDE:
        return _USE_SETTINGS_OVERRIDE.model_copy()  # prevent side-effects
    return BotSettings()


def use_settings(s: BotSettings | None) -> None:
    """
    Overrides the application settings with the given settings object.
    The new settings object is persisted indefinitely until another call to `use_settings` is made.

    :param s: The settings object to use. If None, the application will revert to using the default settings.
    """
    global _USE_SETTINGS_OVERRIDE
    _USE_SETTINGS_OVERRIDE = s.model_copy() if s else s  # prevent side-effects
