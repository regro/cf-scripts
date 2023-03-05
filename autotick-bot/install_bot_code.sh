#!/bin/bash

pushd cf-scripts

mamba install -y --file=requirements/run

export GIT_FULL_HASH=$(git rev-parse HEAD)
pip install -e .
popd

git clone --depth=100 https://github.com/regro/cf-graph-countyfair.git cf-graph
git clone --depth=1 https://github.com/conda-forge/conda-forge-pinning-feedstock.git

echo -e "\n\n============================================\n============================================"
conda info
conda config --show-sources
conda list --show-channel-urls
echo -e "\n\n============================================\n============================================"
