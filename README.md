# cf-scripts
[![Build Status](https://travis-ci.com/regro/cf-scripts.svg?branch=master)](https://travis-ci.com/regro/cf-scripts)

Conda-Forge dependency graph tracker and auto ticker

## Autotick Bot Status and PRs
pull requests: [regro-cf-autotick-bot's PRs](https://github.com/pulls?utf8=%E2%9C%93&q=is%3Aopen+is%3Apr+author%3Aregro-cf-autotick-bot+archived%3Afalse+)

autotick bot status: ![bot](https://github.com/regro/autotick-bot/workflows/bot/badge.svg)

## Setup

Below are instructions for setting up a local installation for testing. They
assume that you have conda installed and conda-forge is in your channel list.

```
conda create -y -n cf --file requirements/run --file requirements/test ipython
source activate cf
python setup.py install
pre-commit run -a
coverage run run_tests.py
```
