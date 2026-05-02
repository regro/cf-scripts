#!/bin/bash

# Environment Variables:
# - CF_FEEDSTOCK_OPS_CONTAINER_NAME: The name of the container image to use for the bot (optional, not used but left intact)
# - CF_FEEDSTOCK_OPS_CONTAINER_TAG: The tag of the container image to use for the bot (optional).
# - CF_TICK_GRAPH_GITHUB_BACKEND_REPO: The GitHub repository to clone cf-graph from. Default: regro/cf-graph-countyfair

# Sets the following environment variables via GITHUB_ENV:
# - CF_FEEDSTOCK_OPS_CONTAINER_NAME (see above)
# - CF_FEEDSTOCK_OPS_CONTAINER_TAG (see above)

set -euo pipefail

git config --global user.name regro-cf-autotick-bot
git config --global user.email 36490558+regro-cf-autotick-bot@users.noreply.github.com
git config --global pull.rebase false

# we pin everything now so no need to update this
# conda update conda-forge-pinning --yes

cd cf-scripts

pip install --no-deps --no-build-isolation -e .

cd ..

clean_disk_space="true"
for arg in "$@"; do
  if [[ "$arg" == "--no-clean-disk-space" ]]; then
    clean_disk_space="false"
  fi
done
if [[ "${clean_disk_space}" == "true" ]]; then
  conda-forge-tick clean-disk-space --ci-service='github-actions'
fi

clone_graph="true"
for arg in "$@"; do
  if [[ "$arg" == "--no-clone-graph" ]]; then
    clone_graph="false"
  fi
done
if [[ "${clone_graph}" == "true" ]]; then
  cf_graph_repo=${CF_TICK_GRAPH_GITHUB_BACKEND_REPO:-"regro/cf-graph-countyfair"}
  cf_graph_remote="https://github.com/${cf_graph_repo}.git"
  # please make sure the cloning depth is always identical to the one used in the integration tests (test_integration.py)
  git clone --depth=5 "${cf_graph_remote}" cf-graph
else
  echo "Skipping cloning of cf-graph"
fi

docker_name=${CF_FEEDSTOCK_OPS_CONTAINER_NAME:-"ghcr.io/regro/conda-forge-tick"}
bot_tag=$(python -c "import conda_forge_tick; print(conda_forge_tick.__version__)")
docker_tag=${CF_FEEDSTOCK_OPS_CONTAINER_TAG:-${bot_tag}}

pull_cont="true"
for arg in "$@"; do
  if [[ "$arg" == "--no-pull-container" ]]; then
    pull_cont="false"
  fi
done
if [[ "${pull_cont}" == "true" ]]; then
  docker pull "${docker_name}:${docker_tag}"
fi

# left intact if already set
export CF_FEEDSTOCK_OPS_CONTAINER_TAG="${docker_tag}"
export CF_FEEDSTOCK_OPS_CONTAINER_NAME="${docker_name}"

echo "CF_FEEDSTOCK_OPS_CONTAINER_TAG=${CF_FEEDSTOCK_OPS_CONTAINER_TAG}" >> "$GITHUB_ENV"
echo "CF_FEEDSTOCK_OPS_CONTAINER_NAME=${CF_FEEDSTOCK_OPS_CONTAINER_NAME}" >> "$GITHUB_ENV"

echo -e "\n\n============================================\n============================================"
conda info
conda config --show-sources
conda list --show-channel-urls
echo -e "\n\n============================================\n============================================"
