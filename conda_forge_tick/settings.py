import os

ENV_GRAPH_REPO = "CF_TICK_GRAPH_GITHUB_BACKEND_REPO"
GRAPH_REPO = os.getenv(ENV_GRAPH_REPO, "regro/cf-graph-countyfair")
"""
The GitHub repository to deploy to. Default: "regro/cf-graph-countyfair".
Overwrite with the environment variable CF_TICK_GRAPH_GITHUB_BACKEND_REPO.
"""

ENV_OVERRIDE_CONDA_FORGE_ORG = "CF_TICK_OVERRIDE_CONDA_FORGE_ORG"
CONDA_FORGE_ORG = os.getenv(ENV_OVERRIDE_CONDA_FORGE_ORG, "conda-forge")
"""
The GitHub organization containing all feedstocks. Default: "conda-forge".
Overwrite with the environment variable CF_TICK_OVERRIDE_CONDA_FORGE_ORG.
"""

ENV_GITHUB_RUNNER_DEBUG = "RUNNER_DEBUG"
GITHUB_RUNNER_DEBUG = os.getenv(ENV_GITHUB_RUNNER_DEBUG, "0") == "1"
"""
Whether we are executing within a GitHub Actions run with debug logging enabled. Default: False.
https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/store-information-in-variables#default-environment-variables
"""

ENV_RANDOM_FRAC_TO_UPDATE = "CF_TICK_RANDOM_FRAC_TO_UPDATE"
RANDOM_FRAC_TO_UPDATE = float(os.getenv(ENV_RANDOM_FRAC_TO_UPDATE, "0.1"))
"""
The fraction of feedstocks (randomly selected) to update in certain jobs. Default: 0.1.
Currently used by update-upstream-versions and make-graph.
In tests, you probably need to set this to 1.0 to update all feedstocks.
"""
