"""
This module contains global settings for the bot.
For each setting available as `SETTING_NAME`, there is an environment variable available as `ENV_SETTING_NAME`
that can be used to override the default value.
Note that there is no further validation of environment variables as of now.
To make settings easier to understand for humans, we use explicit type annotations.
"""

import os

ENV_GRAPH_REPO = "CF_TICK_GRAPH_GITHUB_BACKEND_REPO"
GRAPH_REPO: str = os.getenv(ENV_GRAPH_REPO, "regro/cf-graph-countyfair")
"""
The GitHub repository to deploy to. Default: "regro/cf-graph-countyfair".
Overwrite with the environment variable CF_TICK_GRAPH_GITHUB_BACKEND_REPO.
"""

ENV_OVERRIDE_CONDA_FORGE_ORG = "CF_TICK_OVERRIDE_CONDA_FORGE_ORG"
CONDA_FORGE_ORG: str = os.getenv(ENV_OVERRIDE_CONDA_FORGE_ORG, "conda-forge")
"""
The GitHub organization containing all feedstocks. Default: "conda-forge".
Overwrite with the environment variable CF_TICK_OVERRIDE_CONDA_FORGE_ORG.
"""

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
