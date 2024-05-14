# autotick-bot

[![tests](https://github.com/regro/cf-scripts/actions/workflows/tests.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/tests.yml)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/regro/cf-scripts/master.svg)](https://results.pre-commit.ci/latest/github/regro/cf-scripts/master)
[![bot-bot](https://github.com/regro/cf-scripts/actions/workflows/bot-bot.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-bot.yml)
[![bot-keepalive](https://github.com/regro/cf-scripts/actions/workflows/bot-keepalive.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-keepalive.yml)
[![bot-update-status-page](https://github.com/regro/cf-scripts/actions/workflows/bot-update-status-page.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-update-status-page.yml)
[![bot-pypi-mapping](https://github.com/regro/cf-scripts/actions/workflows/bot-pypi-mapping.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-pypi-mapping.yml)
[![bot-versions](https://github.com/regro/cf-scripts/actions/workflows/bot-versions.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-versions.yml)
[![bot-prs](https://github.com/regro/cf-scripts/actions/workflows/bot-prs.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-prs.yml)
[![bot-feedstocks](https://github.com/regro/cf-scripts/actions/workflows/bot-feedstocks.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-feedstocks.yml)
[![bot-make-graph](https://github.com/regro/cf-scripts/actions/workflows/bot-make-graph.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-make-graph.yml)
[![bot-make-migrators](https://github.com/regro/cf-scripts/actions/workflows/bot-make-migrators.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-make-migrators.yml)
[![bot-cache](https://github.com/regro/cf-scripts/actions/workflows/bot-cache.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-cache.yml)
[![test-model](https://github.com/regro/cf-scripts/actions/workflows/test-model.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/test-model.yml)
[![relock](https://github.com/regro/cf-scripts/actions/workflows/relock.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/relock.yml)

the actual bot in an actual place doing an actual thing

## Table of Contents

- [What has the bot done recently?](#what-has-the-bot-done-recently)
- [Starting and Stopping the Worker](#starting-and-stopping-the-worker)
- [User Documentation](#user-documentation)
- [Developer Documentation](#developer-documentation)

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

## User Documentation

**WARNING: This section is not complete.**

### Configuring the Bot via the `conda-forge.yml`

The primary way to configure the bot for your feedstock is through the `bot` section in the `conda-forge.yml` file at the
root level of your feedstock. Please refer to the [`conda-forge.yml` documentation](https://conda-forge.org/docs/maintainer/conda_forge_yml/#bot) for more details.

### Making Migrators

Bot migrations are used to update large parts of the `conda-forge` ecosystem in a coordinated way. These migrations automate complex maintenance
tasks like add packages to new platforms, adding new versions of Python, R, etc., or updating the global ABI pinnings of key dependencies.

**Unless you need to write a custom migrator, you should wait for the bot to generate the migration itself.**

**If you must write your own migration, try to use the CFEP-09 YAML Migrations in the `conda-forge-pinning-feedstock` before you write a custom class. See the [example](https://github.com/conda-forge/conda-forge-pinning-feedstock/blob/main/recipe/migrations/example.exyaml) migration for more details.**

#### Automated Generation of Migrations

The bot is able to automatically generate most ABI migrations on its own. It will make PRs against the `conda-forge-pinning-feedstock` repository
with the migration YAML file to start the migration. The bot will also make a PR to close the migration once it is mostly complete. The exact conditions under which the bot will close the migration are still being refined and may change.

#### Migration YAML Files and CFEP-09

**WARNING: This section is not complete.**

Sometimes the bot won't be able to generate a migration on its own or the migration is too complex to be fully automated. In this case, you can write your own migration in the form of a YAML file. This YAML file should be placed in the `recipe/migrations` directory of the `conda-forge-pinning-feedstock` repository. From there, the bot will pick up the migration and start it once the PR is merged.

To get started, you can copy the `recipe/migrations/example.exyaml` example file and modify it. The `migration_ts` is the timestamp of the migration and can be created by copying the result of `import time; print(time.time())` from a python interpreter.

Please see the [CFEP-09 implementation](https://github.com/conda-forge/conda-forge-enhancement-proposals/blob/main/cfep-09.md#implementation-details) information for the different kinds of migrations that are available.

#### Custom Migration Classes

Sometimes, the CFEP9 YAML migrations won't precisely fit your needs. In these cases, you can write custom migration classes and submit them as a PR to the bot. Typically, these custom migrations are needed when you need to do tasks like

- Update the internals of the `conda-forge` system (e.g., change how we use compilers, adjust the `conda-forge.yml` schema, etc.)
- Recipe dependency changes that fall outside of CFEP-09 (e.g., renaming a package, swapping a dependency, etc.)

To add a custom migration, follow the following steps.

##### Write your Custom Migration Class

Your `Migration` class should inherit from `conda_forge_tick.migrations.core.Migration`. You should implement the `migrate` method and override any other methods in order to make a good-looking pull request with a correct change to the feedstock.

##### Add your `Migration` to `auto_tick.py`

To have the bot run the migration, we need to add the migrator to add it to the `auto_tick` module.
Typically, this can be done by adding it to the `migrators` list in the `initialize_migrators` function directly.
If your migrator needs special configuration, you should write a new factory function to generate it and add that to the `initialize_migrators` function.

## Developer Documentation

### Useful Environment Variables

- `CF_TICK_GRAPH_DATA_BACKENDS`: See [`LazyJson` Data Structures and Backends](#lazyjson-data-structures-and-backends) below.
- `CF_TICK_GRAPH_DATA_USE_FILE_CACHE`: See [`LazyJson` Data Structures and Backends](#lazyjson-data-structures-and-backends) below.
- `MONGODB_CONNECTION_STRING`: See [`LazyJson` Data Structures and Backends](#lazyjson-data-structures-and-backends) below.
- `CF_TICK_IN_CONTAINER`: set to `true` to indicate that the bot is running in a container, prevents container in container issues
- `TIMEOUT`: set to the number of seconds to wait before timing out the bot
- `RUN_URL`: set to the URL of the CI build (now set to a GHA run URL)
- `MEMORY_LIMIT_GB`: set to the memory limit in GB for the bot
- `BOT_TOKEN`: a GitHub token for the bot user

### Running Tests

The test suite relies on `pytest` and uses `docker`. To run the tests, use the following command:

```bash
pytest -v
```

If you want to test the `container` parts of the bot, you need to build the image first and use the `test` tag:

```bash
docker build -t conda-forge-tick:test .
```

The test suite will not run the container-based tests unless an image with this name and tag is present.

### Debugging Locally

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

### Using the `conda_forge_tick` Module to Interact with the Bot Data

The next few sections provide information about how to use the `conda_forge_tick` package to
interact with the `cf-graph-countyfair` repo.

You will need a copy of `regro/cf-graph-countyfair` and need to be at the root level of the `cf-graph-countyfair` repo
for these code snippets to work properly. You can clone the repo with the following command:

```bash
git clone --depth=1 https://github.com/regro/cf-graph-countyfair.git
```

The `cf-graph-countyfair` repo also has a [notebook](https://github.com/regro/cf-graph-countyfair/blob/master/example.ipynb) with some code examples.

#### Loading the graph

To load the feedstock graph use the ``load_graph`` function

```python
from conda_forge_tick.utils import load_graph
gx = load_graph()
```

Note that all nodes in the graph are backed by `LazyJson` objects associated with the `payload` key which allow for
lazy loading of the node attributes.

```python
print(dict(gx.node['python']['payload']))
```

#### Calculating migration impact

The number of feedstocks which would be migrated by a particular migration can be calculated:

```python
from conda_forge_tick.make_migrators import initialize_migrators
migrators = initialize_migrators()
migrator = migrators[-1]
print(migrator.name)
graph = migrator.graph
# number of packages in the graph to be migrated
print(len(graph))
```

This is an important number to know when proposing a migration

### `conda-forge-tick` Container Image and Dockerfile

The bot relies on a container image to run certain tasks. The image is built from the `Dockerfile` in the root of
this repository and hosted via `ghcr.io`. The `latest` tag is used for production jobs and updated automatically
when PRs are merged. The container is typically run via

```bash
docker run --rm -t conda-forge-tick:latest python /opt/autotick-bot/docker/run_bot_task.py <task> <args>
```

See the [run_bot_task.py](docker/run_bot_task.py) script for more information.

### Data Model

The bot uses the [conda-forge dependency graph](https://github.com/regro/cf-graph-countyfair) to remember metadata
about feedstocks, their versions, and their dependencies. Some of the information
(e.g. the contents of `recipe/meta.yaml` file of the corresponding feedstock) is redundant but stored in the
graph for performance reasons. In an attempt to document the data model, we have created a
[Pydantic](https://github.com/pydantic/pydantic) model in [conda_forge_tick/models](conda_forge_tick/models). Refer
to the README in that directory for more information.

The Pydantic model is not used by the bot code itself (yet) but there is an CI job (`test-models`)
that periodically validates the model against the actual data in the graph.

### `LazyJson` Data Structures and Backends

The bot relies on a lazily-loaded JSON class called `LazyJson` to store and manipulate its data. This data structure has a backend
abstraction that allows the bot to store its data in a variety of places. This system is home-grown and certainly not
ideal.

The backend(s) can be set by using the `CF_TICK_GRAPH_DATA_BACKENDS` environment variable to a colon-separated list of backends (e.g., `export CF_TICK_GRAPH_DATA_BACKENDS=file:mongodb`). The possible backends are:

- `file` (default): Use the local file system to store data. In order to properly use this backend, you must clone the `regro/cf-graph-countyfair` repository and run the bot from `regro/cf-graph-countyfair`'s root directory. You can use the `deploy` command from the bot CLI to commit any changes and push them to the remote repository.
- `mongodb`: Use a MongoDB database to store data. In order to use this backend, you need to set the `MONGODB_CONNECTION_STRING` environment variable to the connection string of the MongoDB database you want to use. **WARNING: The bot will typically read almost all of its data in the backend during its runs, so be careful when using this backend without a pre-cached local copy of the data.**
- `github`: Read-only backend that uses the `regro/cf-graph-countyfair` repository as a data source. This backend reads data on-the-fly using GitHub's "raw" URLs (e.g, `https://raw.githubusercontent.com/regro/cf-graph-countyfair/master/all_feedstocks.json`). This backend is ideal for debugging when you only want to touch a fraction of the data.

The bot uses the first backend in the list as the primary backend and syncs any changed data to the other backends as needed. The bot will also cache data to disk upon first use to speed up subsequent reads. To turn off this caching, set the `CF_TICK_GRAPH_DATA_USE_FILE_CACHE` environment variable to `false`.

### Notes on the `Version` Migrator

The `Version` migrator uses a custom `YAML` parsing class for
`conda` recipes in order to parse the recipe into a form that can be
algorithmically migrated without extensively using regex to change the recipe text
directly. This approach allows us to migrate more complicated recipes.

#### `YAML` Parsing with Jinja2

We use `ruamel.yaml` and `ruamel.yaml.jinja2` to parse the recipe. These
packages ensure that comments (which can contain conda selectors) are kept. They
also ensure that any `jinja2` syntax is parsed correctly. Further, for
duplicate keys in the `YAML`, but with different conda selectors, we collapse
the selector into the key. Finally, we use the `jinja2` AST to find all
simple `jinja2` `set` statements. These are parsed into a dictionary for later
use.

You can access the parser and parsed recipe via

```python
from conda_forge_tick.recipe_parser import CondaMetaYAML

cmeta = CondaMetaYAML(meta_yaml_as_string)

# get the jinja2 vars
for key, v in cmeta.jinja2_vars.items():
    print(key, v)

# print a section of the recipe
print(cmeta.meta["extra"])
```

Note that due to conda selectors and our need to deduplicate keys, any keys
with selectors will look like `"source__###conda-selector###__win or osx"`.
You can access the middle token for selectors at `conda_forge_tick.recipe_parser.CONDA_SELECTOR`.

It is useful to write generators if you want all keys possibly with selectors

```python
def _gen_key_selector(dct: MutableMapping, key: str):
    for k in dct:
        if (
            k == key
            or (
                CONDA_SELECTOR in k and
                k.split(CONDA_SELECTOR)[0] == key
            )
        ):
            yield k

for key in _gen_key_selector(cmeta.meta, "source"):
    print(cmeta.meta[key])
```

#### Version Migration Algorithm

Given the parser above, we migrate recipes via the following algorithm.

1. We compile all selectors in the recipe by recursively traversing
   the `meta.yaml`. We also insert `None` into this set to represent no
   selector.
2. For each selector, we pull out all `url`, hash-type key, and all `jinja2`
   variables with the selector. If none with the selector are found, we default to
   any ones without a selector.
3. For each of the sets of items in step 2 above, we then try and update the
   version and get a new hash for the `url`. We also try common variations
   in the `url` at this stage.
4. Finally, if we can find new hashes for all of the `urls` for each selector,
   we call the migration successful and submit a PR. Otherwise, no PR is submitted.
