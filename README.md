# autotick-bot
[![tests](https://github.com/regro/cf-scripts/actions/workflows/tests.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/tests.yml)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/regro/cf-scripts/master.svg)](https://results.pre-commit.ci/latest/github/regro/cf-scripts/master)
[![bot-bot](https://github.com/regro/cf-scripts/actions/workflows/bot-bot.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-bot.yml)
[![bot-update-status-page](https://github.com/regro/cf-scripts/actions/workflows/bot-update-status-page.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-update-status-page.yml)
[![bot-pypi-mapping](https://github.com/regro/cf-scripts/actions/workflows/bot-pypi-mapping.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-pypi-mapping.yml)
[![bot-versions](https://github.com/regro/cf-scripts/actions/workflows/bot-versions.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-versions.yml)
[![bot-prs](https://github.com/regro/cf-scripts/actions/workflows/bot-prs.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-prs.yml)
[![bot-feedstocks](https://github.com/regro/cf-scripts/actions/workflows/bot-feedstocks.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-feedstocks.yml)
[![bot-delete-old-runs](https://github.com/regro/cf-scripts/actions/workflows/bot-delete-old-runs.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-delete-old-runs.yml)
[![bot-make-graph](https://github.com/regro/cf-scripts/actions/workflows/bot-make-graph.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-make-graph.yml)
[![bot-cache](https://github.com/regro/cf-scripts/actions/workflows/bot-cache.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-cache.yml)
[![relock](https://github.com/regro/cf-scripts/actions/workflows/relock.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/relock.yml)

the actual bot in an actual place doing an actual thing

## Starting and Stopping the Worker

In order to start the worker, make a commit to master with the file `please.go`
in the `autotick-bot` subdirectory.

If you want to stop the worker, rename the file to `please.stop` and it will not restart
itself on the next round.


## Debugging Locally
You can use the CLI of the bot to debug it locally. To do so, install the bot with the following command:
```bash
pip install -e .
```

Then you can use the CLI like this:
```bash
conda-forge-tick --help
```

For debugging, use the `--debug` flag. This enables debug logging and disables multiprocessing.

Note that the bot expects the [conda-forge dependency graph](https://github.com/regro/cf-graph-countyfair) to be
present in the current working directory by default, unless the `--online` flag is used.

> [!TIP]
> Use the `--online` flag when debugging the bot locally to avoid having to clone the whole
> dependency graph.

The local debugging functionality is still work in progress and might not work for all commands.
Currently, the following commands are supported and tested:
- `update-upstream-versions`

## Data Model
The bot uses the [conda-forge dependency graph](https://github.com/regro/cf-graph-countyfair) to remember metadata
about feedstocks, their versions, and their dependencies. Some of the information
(e.g. the contents of `recipe/meta.yaml` file of the corresponding feedstock) is redundant but stored in the
graph for performance reasons. In an attempt to document the data model, we have created a
[Pydantic](https://github.com/pydantic/pydantic) model in [conda_forge_tick/models](conda_forge_tick/models). Refer
to the README in that directory for more information.

The Pydantic model is not used by the bot code itself (yet) but there is an CI job (`test-models`)
that periodically validates the model against the actual data in the graph.

## What has the bot done recently?

Check out its [PRs](https://github.com/pulls?utf8=%E2%9C%93&q=is%3Aopen+is%3Apr+author%3Aregro-cf-autotick-bot+archived%3Afalse+), its currently [running jobs](https://github.com/regro/cf-scripts/actions?query=is%3Ain_progress++), and the [status page](https://conda-forge.org/status/#current_migrations)!
