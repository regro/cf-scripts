#!/bin/bash

git config --global user.name regro-cf-autotick-bot
git config --global user.email 36490558+regro-cf-autotick-bot@users.noreply.github.com
git config --global pull.rebase false

cd cf-scripts

export GIT_FULL_HASH=$(git rev-parse HEAD)
pip install -e .

cd ..

if [[ "$1" != "--no-clone-graph-and-pinning" ]]; then
    git clone --depth=10 https://github.com/regro/cf-graph-countyfair.git cf-graph
    git clone --depth=1 https://github.com/conda-forge/conda-forge-pinning-feedstock.git
else
    echo "Skipping cloning of cf-graph and pinning feedstock"
fi

echo -e "\n\n============================================\n============================================"
conda info
conda config --show-sources
conda list --show-channel-urls
echo -e "\n\n============================================\n============================================"
