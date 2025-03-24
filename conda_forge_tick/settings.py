"""
This module contains global settings for the bot.
For each setting available as `SETTING_NAME`, there is an environment variable available as `ENV_SETTING_NAME`
that can be used to override the default value.
Note that there is no further validation of environment variables as of now.
To make settings easier to understand for humans, we use explicit type annotations.
"""

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENVIRONMENT_PREFIX = "CF_TICK_"
"""
All environment are expected to be prefixed with this.
"""

ENV_CONDA_FORGE_ORG = ENVIRONMENT_PREFIX + "CONDA_FORGE_ORG"
"""
The environment variable used to set the `conda_forge_org` setting.
Note: This must match the field name in the `BotSettings` class.
"""


class BotSettings(BaseSettings):
    """
    The global settings for the bot.

    To configure a settings value, set the corresponding environment variable with the prefix `CF_TICK_`.
    For example, to set the `graph_github_backend_repo` setting, set the environment variable
    `CF_TICK_GRAPH_GITHUB_BACKEND_REPO`.

    To access the current settings object, please use the `settings()` function.
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


def settings() -> BotSettings:
    """
    Get the current settings object.
    """
    return BotSettings()


ENV_GITHUB_RUNNER_DEBUG = "RUNNER_DEBUG"
GITHUB_RUNNER_DEBUG: bool = os.getenv(ENV_GITHUB_RUNNER_DEBUG, "0") == "1"
"""
Whether we are executing within a GitHub Actions run with debug logging enabled. Default: False.
https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/store-information-in-variables#default-environment-variables
"""

ENV_FRAC_UPDATE_UPSTREAM_VERSIONS = "CF_TICK_FRAC_UPDATE_UPSTREAM_VERSIONS"
FRAC_UPDATE_UPSTREAM_VERSIONS: float = float(
    os.getenv(ENV_FRAC_UPDATE_UPSTREAM_VERSIONS, "0.1")
)
"""
The fraction of feedstocks (randomly selected) to update in the update-upstream-versions job.
This is currently only respected when running concurrently (via process pool), not in sequential mode.
Therefore, you don't need to set this when debugging locally.
"""

ENV_RANDOM_FRAC_MAKE_GRAPH = "CF_TICK_FRAC_MAKE_GRAPH"
FRAC_MAKE_GRAPH: float = float(os.getenv(ENV_RANDOM_FRAC_MAKE_GRAPH, "0.1"))
"""
The fraction of feedstocks (randomly selected) to update in the make-graph job.
In tests or when debugging, you probably need to set this to 1.0 to update all feedstocks.
"""
