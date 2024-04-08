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

## What has the bot done recently?

Check out the following pages for status information on the bot:

- [PRs](https://github.com/pulls?utf8=%E2%9C%93&q=is%3Aopen+is%3Apr+author%3Aregro-cf-autotick-bot+archived%3Afalse+)
- [running jobs](https://github.com/regro/cf-scripts/actions?query=is%3Ain_progress++)
- [status page](https://conda-forge.org/status/#current_migrations)

## Starting and Stopping the Worker

In order to start the worker, make a commit to master with the file `please.go`
in the `autotick-bot` subdirectory.

If you want to stop the worker, rename the file to `please.stop`, and it will not restart
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

## `conda-forge-tick` Container Image and Dockerfile

The bot relies on a container image to run certain tasks. The image is built from the `Dockerfile` in the root of
this repository and hosted via `ghcr.io`. The `latest` tag is used for production jobs and updated automatically
when PRs are merged. The container is typically run via

```bash
docker run --rm -t conda-forge-tick:latest python /opt/autotick-bot/docker/run_bot_task.py <task> <args>
```

See the [run_bot_task.py](docker/run_bot_task.py) script for more information.

## `LazyJson` Data Structures and Backends

The bot relies on a lazily-loaded JSON class called `LazyJson` to store and manipulate its data. This data structure has a backend
abstraction that allows the bot to store its data in a variety of places. This system is home-grown and certainly not
ideal.

The backend(s) can be set by using the `CF_TICK_GRAPH_DATA_BACKENDS` environment variable to a colon-separated list of backends (e.g., `export CF_TICK_GRAPH_DATA_BACKENDS=file:mongodb`). The possible backends are:

- `file` (default): Use the local file system to store data. In order to properly use this backend, you must clone the `regro/cf-graph-countyfair` repository and run the bot from `regro/cf-graph-countyfair`'s root directory. You can use the `deploy` command from the bot CLI to commit any changes and push them to the remote repository.
- `mongodb`: Use a MongoDB database to store data. In order to use this backend, you need to set the `MONGODB_CONNECTION_STRING` environment variable to the connection string of the MongoDB database you want to use. **WARNING: The bot will typically read almost all of its data in the backend during its runs, so be careful when using this backend without a pre-cached local copy of the data.**
- `github`: Read-only backend that uses the `regro/cf-graph-countyfair` repository as a data source. This backend reads data on-the-fly using GitHub's "raw" URLs (e.g, `https://raw.githubusercontent.com/regro/cf-graph-countyfair/master/all_feedstocks.json`). This backend is ideal for debugging when you only want to touch a fraction of the data.

The bot uses the first backend in the list as the primary backend and syncs any changed data to the other backends as needed. The bot will also cache data to disk upon first use to speed up subsequent reads. To turn off this caching, set the `CF_TICK_GRAPH_DATA_USE_FILE_CACHE` environment variable to `false`.
