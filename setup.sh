#!/usr/bin/env bash

export START_TIME="$(date +%s)"
export TIMEOUT=2700
wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh -O miniconda.sh
chmod +x miniconda.sh
./miniconda.sh -b -p ~/mc
export PATH=~/mc/bin:$PATH
conda config --set always_yes yes --set changeps1 no --set quiet true
conda config --add channels conda-forge
conda update conda --yes

export GIT_FULL_HASH=`git rev-parse HEAD`
conda install python=$TRAVIS_PYTHON_VERSION
conda install --file requirements/run
python setup.py develop
cd ..
git clone https://github.com/regro/cf-graph.git

set -e
