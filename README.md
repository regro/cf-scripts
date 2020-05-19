# cf-scripts
[![Build Status](https://travis-ci.org/regro/cf-scripts.svg?branch=master)](https://travis-ci.org/regro/cf-scripts)

Conda-Forge dependency graph tracker and auto ticker


## Autotick Bot Status and PRs
pull requests: [regro-cf-autotick-bot's PRs](https://github.com/pulls?utf8=%E2%9C%93&q=is%3Aopen+is%3Apr+author%3Aregro-cf-autotick-bot+archived%3Afalse+)

autotick bot status: [![CircleCI](https://circleci.com/gh/regro/circle_worker.svg?style=svg)](https://circleci.com/gh/regro/circle_worker)

## Plan
The auto-tick bot runs on circleCI via the [circle_worker](https://github.com/regro/circle_worker) repo.

The bot has various stages where it:
1. gets the names of all the conda-forge feedstocks `all_feedstocks.py`
1. pulls all the recipe `meta.yaml` data associated with the feedstocks `make_graph.py`
1. gets the upstream versions `update_upstream_versions.py`
1. issues PRs if packages are out of date, or need to be migrated `auto_tick.xsh`
1. writes out the status of all active migrations `status_report.py`
1. deploys the data back to [cf-graph](https://github.com/regro/cf-graph-countyfair) `cli.xsh`

## Setup

Below are instructions for setting up a local installation for testing. They
assume that you have conda installed and conda-forge is in your channel list.

```
conda create -y -n cf --file requirements/run --file requirements/test ipython
source activate cf
python setup.py install
coverage run run_tests.py
```
