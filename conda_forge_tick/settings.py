import os

DEPLOY_REPO = os.getenv("DEPLOY_REPO", "regro/cf-graph-countyfair")
"""
The GitHub repository to deploy to. Default: "regro/cf-graph-countyfair".
Overwrite with the environment variable DEPLOY_REPO.
"""
