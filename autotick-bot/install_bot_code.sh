#!/bin/bash

if [[ "$1" != "--no-clean-disk-space" ]] && [[ "$2" != "--no-clean-disk-space" ]]; then
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
  sudo apt-get purge -y -f firefox \
                          google-chrome-stable \
                          microsoft-edge-stable
  sudo apt-get autoremove -y >& /dev/null
  sudo apt-get autoclean -y >& /dev/null
  sudo docker image prune --all --force
  df -h
fi

git config --global user.name regro-cf-autotick-bot
git config --global user.email 36490558+regro-cf-autotick-bot@users.noreply.github.com
git config --global pull.rebase false

conda update conda-forge-pinning --yes

cd cf-scripts

pip install --no-deps --no-build-isolation -e .

cd ..

if [[ "$1" != "--no-clone-graph" ]] && [[ "$2" != "--no-clone-graph" ]]; then
  git clone --depth=5 https://github.com/regro/cf-graph-countyfair.git cf-graph
else
  echo "Skipping cloning of cf-graph"
fi

bot_tag=$(python -c "import conda_forge_tick; print(conda_forge_tick.__version__)")
docker_tag=${CF_FEEDSTOCK_OPS_CONTAINER_TAG:-${bot_tag}}
docker pull ghcr.io/regro/conda-forge-tick:${docker_tag}

export CF_FEEDSTOCK_OPS_CONTAINER_TAG=${docker_tag}
export CF_FEEDSTOCK_OPS_CONTAINER_NAME="ghcr.io/regro/conda-forge-tick"

echo "CF_FEEDSTOCK_OPS_CONTAINER_TAG=${CF_FEEDSTOCK_OPS_CONTAINER_TAG}" >> "$GITHUB_ENV"
echo "CF_FEEDSTOCK_OPS_CONTAINER_NAME=${CF_FEEDSTOCK_OPS_CONTAINER_NAME}" >> "$GITHUB_ENV"

echo -e "\n\n============================================\n============================================"
conda info
conda config --show-sources
conda list --show-channel-urls
echo -e "\n\n============================================\n============================================"
