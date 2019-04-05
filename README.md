# cf-scripts
Conda-Forge dependency graph tracker and auto ticker

[regro-cf-autotick-bot's PRs](https://github.com/pulls?utf8=%E2%9C%93&q=is%3Aopen+is%3Apr+author%3Aregro-cf-autotick-bot+archived%3Afalse+) 

## Status
[![CircleCI](https://circleci.com/gh/regro/circle_worker.svg?style=svg)](https://circleci.com/gh/regro/circle_worker)

## Plan
The auto-tick bot runs on circleCI via the [circle_worker](https://github.com/regro/circle_worker) repo.

The bot has various stages where it:
1. gets the names of all the conda-forge feedstocks
1. pulls all the recipe `meta.yaml` data associated with the feedstocks
1. gets the upstream versions
1. issues PRs if packages are out of date, or need to be migrated
1. writes out the status of all active migrations
1. deploys the data back to [cf-graph](https://github.com/regro/cf-graph3)

## Setup

Below are instructions for setting up a local installation for testing. They
assume that you have conda installed and conda-forge is in your channel list.

```
conda create -y -n cf --file requirements/run --file requirements/test ipython
source activate cf
python setup.py install
coverage run run_tests.py
```
