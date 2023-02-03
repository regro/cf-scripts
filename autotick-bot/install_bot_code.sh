#!/bin/bash

# conda config --set experimental_solver libmamba
# conda deactivate
# mamba install conda-libmamba-solver "conda>=4.12.0" --yes --quiet
# conda activate test
# mamba install conda-libmamba-solver "conda>=4.12.0" --yes --quiet

export START_TIME=$(date +%s)
export TIMEOUT=7200

git clone --depth=1 https://github.com/regro/cf-scripts.git

pushd cf-scripts
export GIT_FULL_HASH=$(git rev-parse HEAD)
mamba create -n run_env --yes --quiet curl python=3.9
conda activate run_env
for i in `seq 1 10`; do
  echo $i
  mamba install --quiet --yes --file requirements/run || echo 'mamba install failed!'
done
mamba install --quiet --yes --file requirements/run
# mamba install conda-libmamba-solver "conda>=4.12.0" --yes --quiet
conda config --env --set add_pip_as_python_dependency False
conda info
conda config --show-sources
conda list --show-channel-urls
python setup.py develop
popd

git clone --depth=100 https://github.com/regro/cf-graph-countyfair.git cf-graph
git clone --depth=1 https://github.com/conda-forge/conda-forge-pinning-feedstock.git
