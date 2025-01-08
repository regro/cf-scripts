import os

DEPLOY_REPO = os.getenv(
    "CF_TICK_GRAPH_GITHUB_BACKEND_REPO", "regro/cf-graph-countyfair"
)
"""
The GitHub repository to deploy to. Default: "regro/cf-graph-countyfair".
Overwrite with the environment variable CF_TICK_GRAPH_GITHUB_BACKEND_REPO.
"""

CONDA_FORGE_ORG = os.getenv("CF_TICK_OVERRIDE_CONDA_FORGE_ORG", "conda-forge")
"""
The GitHub organization containing all feedstocks. Default: "conda-forge".
Overwrite with the environment variable CF_TICK_OVERRIDE_CONDA_FORGE_ORG.
"""
