# scripts and bot repo
This repo is now the home of the autotick bot (used to be at [regro/autotick-bot](https://github.com/regro/autotick-bot)) and remains the home of all of the code that powers the bot (under the `conda_forge_tick/` subdir).

See [autotick-bot](#autotick-bot) section for info on the bot.

See [cf-scripts](#cf-scripts) heading for info on the code that powers the bot.

# autotick-bot
[![update-status-page](https://github.com/regro/cf-scripts/workflows/bot-update-status-page/badge.svg)](https://github.com/regro/cf-scripts/actions?query=workflow%3Abot-update-status-page)
[![pypi-mapping](https://github.com/regro/cf-scripts/workflows/bot-pypi-mapping/badge.svg)](https://github.com/regro/cf-scripts/actions?query=workflow%3Abot-pypi-mapping)
[![versions](https://github.com/regro/cf-scripts/workflows/bot-versions/badge.svg)](https://github.com/regro/cf-scripts/actions?query=workflow%3Abot-versions)
[![prs](https://github.com/regro/cf-scripts/workflows/bot-prs/badge.svg)](https://github.com/regro/cf-scripts/actions?query=workflow%3Abot-prs)
[![bot](https://github.com/regro/cf-scripts/workflows/bot-bot/badge.svg)](https://github.com/regro/cf-scripts/actions?query=workflow%3Abot-bot)
[![feedstocks](https://github.com/regro/cf-scripts/workflows/bot-feedstocks/badge.svg)](https://github.com/regro/cf-scripts/actions?query=workflow%3Abot-feedstocks)
[![delete-old-runs](https://github.com/regro/cf-scripts/actions/workflows/bot-delete-old-runs.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-delete-old-runs.yml)

the actual bot in an actual place doing an actual thing

## Starting and Stopping the Worker

In order to start the worker, make a commit to master with the file `please.go`
in the `autotick-bot` subdirectory.

If you want to stop the worker, simply delete this file and it will not restart
itself on the next round. When stopping the worker, make sure to add `ci skip` to the commit message.

## What has the bot done recently?

Check out its [PRs](https://github.com/pulls?utf8=%E2%9C%93&q=is%3Aopen+is%3Apr+author%3Aregro-cf-autotick-bot+archived%3Afalse+), its currently [running jobs](https://github.com/regro/cf-scripts/actions?query=is%3Ain_progress++), and the [status page](https://conda-forge.org/status/#current_migrations)!


# cf-scripts
[![tests](https://github.com/regro/cf-scripts/workflows/tests/badge.svg)](https://github.com/regro/cf-scripts/actions?query=workflow%3Atests)

Conda-Forge dependency graph tracker and auto ticker

## Autotick Bot Status and PRs
pull requests: [regro-cf-autotick-bot's PRs](https://github.com/pulls?utf8=%E2%9C%93&q=is%3Aopen+is%3Apr+author%3Aregro-cf-autotick-bot+archived%3Afalse+)

autotick bot status: [![bot](https://github.com/regro/cf-scripts/workflows/bot/badge.svg)](https://github.com/regro/cf-scripts/actions?query=workflow%3Abot)

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
