#!/bin/bash

# Environment Variables:
# - CF_TICK_CONTAINER_TAG: The tag of the container to use for the bot (optional).
# - CF_GRAPH_REMOTE: The URL to clone the cf-graph repository from (optional).
# - CF_PINNING_REMOTE: The URL to clone the conda-forge-pinning-feedstock repository from (optional).
# - PRUNE_DOCKER: Whether to prune docker images (optional, default is true).
# - PULL_DOCKER: Whether to pull the conda-forge-tick Docker image from GHCR (optional, default is true).

set -euxo pipefail

# clean disk space
sudo mkdir -p /opt/empty_dir || true
for d in \
 /opt/ghc \
 /opt/hostedtoolcache \
 /usr/lib/jvm \
 /usr/local/.ghcup \
 /usr/local/lib/android \
 /usr/local/share/powershell \
 /usr/share/dotnet \
 /usr/share/swift \
; do
  sudo rsync --stats -a --delete /opt/empty_dir/ $d || true
done

# dpkg does not fail if the package is not installed
sudo dpkg --remove firefox \
    google-chrome-stable \
    microsoft-edge-stable
sudo apt-get autoremove -y >& /dev/null
sudo apt-get autoclean -y >& /dev/null

if [[ ${PRUNE_DOCKER:-true} == "true" ]]; then
    sudo docker image prune --all --force
fi

df -h

git config --global user.name regro-cf-autotick-bot
git config --global user.email 36490558+regro-cf-autotick-bot@users.noreply.github.com
git config --global pull.rebase false

conda update conda-forge-pinning --yes

cd cf-scripts

pip install --no-deps --no-build-isolation -e .

cd ..

if [[ "$#" -lt 1 ]] || [[ "$1" != "--no-clone-graph-and-pinning" ]]; then
    cf_graph_remote=${CF_GRAPH_REMOTE:-"https://github.com/regro/cf-graph-countyfair.git"}
    cf_pinning_remote=${CF_PINNING_REMOTE:-"https://github.com/conda-forge/conda-forge-pinning-feedstock.git"}
    git clone --depth=5 "${cf_graph_remote}" cf-graph
    git clone --depth=1 "${cf_pinning_remote}"
else
    echo "Skipping cloning of cf-graph and pinning feedstock"
fi

if [[ ${PULL_DOCKER:-true} == "true" ]]; then
    bot_tag=$(python -c "import conda_forge_tick; print(conda_forge_tick.__version__)")
    docker_tag=${CF_TICK_CONTAINER_TAG:-${bot_tag}}
    docker pull ghcr.io/regro/conda-forge-tick:${docker_tag}
fi

echo -e "\n\n============================================\n============================================"
conda info
conda config --show-sources
conda list --show-channel-urls
echo -e "\n\n============================================\n============================================"
