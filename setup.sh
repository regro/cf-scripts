#!/usr/bin/env bash

wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh
chmod +x miniconda.sh
./miniconda.sh -b -p ~/mc
export PATH=~/mc/bin:$PATH
conda config --set always_yes yes --set changeps1 no --set quiet true
conda config --add channels conda-forge
conda update conda --yes

export GIT_FULL_HASH=`git rev-parse HEAD`
conda install python=$TRAVIS_PYTHON_VERSION
git clone https://github.com/regro/cf-scripts.git
git clone https://github.com/regro/cf-graph.git
cd cf-graph
conda install --file ../cf-scripts/requirements/run

set -e
