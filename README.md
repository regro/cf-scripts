# autotick-bot

[![tests](https://github.com/regro/cf-scripts/actions/workflows/tests.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/tests.yml)
[![pre-commit.ci status](https://results.pre-commit.ci/badge/github/regro/cf-scripts/main.svg)](https://results.pre-commit.ci/latest/github/regro/cf-scripts/main)
[![relock](https://github.com/regro/cf-scripts/actions/workflows/relock.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/relock.yml)
[![bot-bot](https://github.com/regro/cf-scripts/actions/workflows/bot-bot.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-bot.yml)
[![bot-keepalive](https://github.com/regro/cf-scripts/actions/workflows/bot-keepalive.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-keepalive.yml)
[![bot-update-status-page](https://github.com/regro/cf-scripts/actions/workflows/bot-update-status-page.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-update-status-page.yml)
[![bot-pypi-mapping](https://github.com/regro/cf-scripts/actions/workflows/bot-pypi-mapping.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-pypi-mapping.yml)
[![bot-versions](https://github.com/regro/cf-scripts/actions/workflows/bot-versions.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-versions.yml)
[![bot-prs](https://github.com/regro/cf-scripts/actions/workflows/bot-prs.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-prs.yml)
[![bot-feedstocks](https://github.com/regro/cf-scripts/actions/workflows/bot-feedstocks.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-feedstocks.yml)
[![bot-make-graph](https://github.com/regro/cf-scripts/actions/workflows/bot-make-graph.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-make-graph.yml)
[![bot-update-nodes](https://github.com/regro/cf-scripts/actions/workflows/bot-update-nodes.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-update-nodes.yml)
[![bot-make-migrators](https://github.com/regro/cf-scripts/actions/workflows/bot-make-migrators.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-make-migrators.yml)
[![bot-cache](https://github.com/regro/cf-scripts/actions/workflows/bot-cache.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/bot-cache.yml)
[![test-model](https://github.com/regro/cf-scripts/actions/workflows/test-model.yml/badge.svg)](https://github.com/regro/cf-scripts/actions/workflows/test-model.yml)


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

In order to start the worker, make a commit to main with the file `please.go`
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

Please see the [CFEP-09 implementation](https://github.com/conda-forge/conda-forge-enhancement-proposals/blob/main/cfep-09.md#implementation-details) information for the different kinds of migrations that are available. As of writing, `deletion` migrations are not yet implemented. There are additional migration types not in CFEP-09, but defined directly in `conda-smithy`. See the `__migration.operation` field and the [source code](https://github.com/conda-forge/conda-smithy/blob/main/conda_smithy/variant_algebra.py) in `conda-smithy` for more information.

Here is full example migration file with the various possible keys and their meanings:

```yaml
# The timestamp of when the migration was made
# Can be obtained by copying the output of
# python -c "import time; print(f'{time.time():.0f}')"
migrator_ts: 1634025600

# The __migrator key is used to determine the type of migration, special behavior, etc.
__migrator:
  # The kind of of migrator. Only version is supported at the moment.
  kind: version

  # The operation key forces the migrator to do specific operations.
  # This key is mutually exclusive with the `kind` key.
  operation: key_add  # add the keys to the pinnings
  operation: key_remove  # remove the keys from the pinnings

  # The migration number denotes specific runs of the migration, like a
  # package build number. Changing it will cause the migration to start over.
  # Only change the migration_number if the bot messes up,
  migration_number: 1

  # `build_number` determines the increment to the build number when the
  # migration runs.
  # Change this to zero if the new pin only adds builds to the feedstock
  # and doesn't rebuild any existing packages.
  bump_number: 1

  # If `paused` is set to true, the bot will not run the migration. This key is
  # useful if we do not want to delete the migration file from the pinnings repo,
  # but we do not want to run the migration.
  paused: false

  # If a migration is marked as longterm, the status page will filter the migration
  # information up to the top. This is useful for migrations that will take a long
  # time (e.g., python) and so merit special attention.
  longterm: false

  # If `automerge` is set to true, the bot will automatically merge the PRs that pass.
  # This can be used in conjunction with the solver to checks to fully automate migrations.
  automerge: false

  # Set `exclude` to a list of feedstocks to exclude from the migration.
  exclude:
    - feedstock1
    - feedstock2

  # If `exclude_pinned_pkgs` is set to true, the bot will exclude feedstocks that
  # make the packages whose pins are being moved (i.e., the packages and versions listed below).
  # Usually this behavior is the correct default.
  exclude_pinned_pkgs: true

  # If `include_noarch` is set to true, the bot will include noarch feedstocks in the migration.
  # The bot will skip noarch feedstocks by default.
  include_noarch: false

  # If `include_build` is set to true, the bot will include build requirements in the migration.
  # The bot will skip build requirements by default, which prevents compiler migrations.
  include_build: false

  # The pr_limit controls how many PRs that bot makes in a single run.
  # Typical values range from 5 (small/slow) to 30 (large/fast). If not given,
  # the bot will scale this limit automatically to make new migrations more responsive
  # and to ensure that migrations start slowly to prevent the negative impacts
  # of buggy migrations.
  pr_limit: 5

  # If `check_solvable` is set to true, the bot will check if the migrated feedstock
  # environments can be solved by the solver. If they cannot, the bot will not make a PR.
  # This feature is useful for migrations that use automerge and to prevent the bot
  # from issuing PRs that will fail to build.
  check_solvable: true

  # The `allowlist_file` field can be used to limit a migrator to a specific
  # list of target packages and their dependencies. The target packages are
  # listed in a simple text file format, one package per line. The file should
  # be placed in the `migration_support` directory. This is useful for
  # throtteling potentially large migrations, for example to avoid overloading
  # the CI, to phase subsections of the ecosystem, or to lower risk. Examples
  # include migrations for new architectures.
  allowlist_file: boostallow.txt

  # The bot will forcibly make PRs for feedstocks that have failed the solver attempts after
  # this many tries.
  force_pr_after_solver_attempts: 10

  # If `override_cbc_keys` is set to a list, the bot will use this list of packages to
  # determine which feedstocks to migrate as opposed to the changed pins listed below.
  # You almost never need this option.
  override_cbc_keys:
    - package1
    - package2

  # If this key is set to dict, the conda-forge.yml will be modified by the migration
  # with the contents of this dict. This can be used to add keys to the conda-forge.yml
  # or to change them. You can replace subkeys by using a dot in the key name (e.g., `a.b.c`
  # will replace the value of `c`, but leave `a` and `b` untouched).
  conda_forge_yml_patches:
    blah.foo: false
    bar: 1

  # If this key is set to dict mapping a feedstock to a list of feedstocks, the bot will
  # ignore predecessors in the list for the feedstock in the key when determining if the
  # a feedstock is ready to be migrated. This can be used to force a specific feedstock to be
  # migrated even if not all of its predecessors have been migrated.
  ignored_deps_per_node:
    feedstock1:
      - feedstock2
      - feedstock3

  # The `ordering` field is used to determine where to insert keys for `key_add` migrations
  # or which keys to keep for version migrations where the versions are strings and so have no
  # natural version ordering. Each changed pin can be mapped to a list
  # that determines the ordering. The highest (e.g., item with highest list index)
  # version is kept for version migrations.
  ordering:
    pin1:
      - value1
      - value2
    pin2:
      - value3
      - value4

# The names of any packages/pins you wish to migrate go here. Convert any
# dashes to underscores. You can list more than one item here if things are
# coupled or if you need to change items in zip_keys via key_add or key_remove.
boost_cpp:
  - 1.71    # new version to build against
```

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
- `CF_FEEDSTOCK_OPS_IN_CONTAINER`: set to `true` to indicate that the bot is running in a container, prevents container in container issues
- `TIMEOUT`: set to the number of seconds to wait before timing out the bot
- `RUN_URL`: set to the URL of the CI build (now set to a GHA run URL)
- `MEMORY_LIMIT_GB`: set to the memory limit in GB for the bot
- `BOT_TOKEN`: a GitHub token for the bot user
- `CF_FEEDSTOCK_OPS_CONTAINER_NAME`: the name of the container to use in the bot, otherwise defaults to `ghcr.io/regro/conda-forge-tick`
- `CF_FEEDSTOCK_OPS_CONTAINER_TAG`: set this to override the default container tag used in production runs, otherwise the value of `__version__` is used
- `CF_TICK_USE_LOCAL_PINNINGS`: set to `true` to force the bot to always use the local copy of the pinnings file for rerenders, set during integration testing

Additional environment variables are described in [the settings module](conda_forge_tick/settings.py).

### Getting a Working Environment

The bot has an abstract set of requirements stored in the `environment.yml` file in this repo.

It's production environment is locked via `conda-lock`. The lockfile is stored in `cf-scripts`
at [https://github.com/regro/cf-scripts/blob/main/conda-lock.yml](https://github.com/regro/cf-scripts/blob/main/conda-lock.yml).
The production environment is relocked regularly using a GitHub Actions [job](https://github.com/regro/cf-scripts/actions/workflows/relock.yaml).

There are two ways to get a working environment:

1. Use the `environment.yml` file in the repo with `conda env`.
2. Download the lockfile and use `conda-lock`. The best way to download the lockfile is via `wget` or `curl` or similar:

   ```bash
   wget https://raw.githubusercontent.com/regro/cf-scripts/main/conda-lock.yml
   ```

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
> dependency graph. With `--no-containers`, you disable the functionality of running sensitive tasks in a Docker
> container, which may be helpful for debugging.

The local debugging functionality is still work in progress and might not work for all commands.
Currently, the following commands are supported and tested:

- `update-upstream-versions`

### Integration Tests

See [tests_integration/README.md](tests_integration/README.md).

### Structure of the Bot's Jobs

#### History

The bot started mostly as a single script, in `xonsh`, that was run in a cron-like job that would do all tasks. Further, given the small size of the bot's metadata at the time, the initial bot code assumed that all data was present on disk locally, could be loaded into memory efficiently, and that all parts of the code could modify almost any part of the data. Given the small size of `conda-forge` at the time, this model was workable, had the advantage of simplicity, and had the advantage of ensuring strong consistency between the different parts of the bot's data.

As `conda-forge` grew, the "single job + global data access" model became increasingly unmanageable. Thus, over time, the bot has been split into separate jobs that run in parallel. This gradual refactoring has maintained the bot's performance despite `conda-forge`'s extreme growth. The cost has been increased complexity, the need to more carefully manage data access/updates, and the loss of strong consistency between the different parts of the bot's data. As of 2024, the bot is a collection of cron jobs, run in parallel, combined with a carefully separated data model based on eventual consistency.

#### Current Bot Jobs and Structure

[**Current GitHub Runner Allocation**](docs/runner_allocation.md)

In this section, we list the collection of jobs that comprise the bot. Each job touches a distinct part of the bot's data structure and is run in parallel with the other jobs. We have also specified the GitHub Actions workflow that runs each job. See those files for further details on which commands are run.

**bot** / `bot-bot.yml`: The main job that runs the bot, making PRs to feedstocks, etc. This job writes data on the PRs it makes to `cf-graph-countyfair/pr_info` and `cf-graph-countyfair/version_pr_info`. It also writes new PR JSON blobs to `cf-graph-countyfair/pr_json` for each PR to track their statuses on GitHub.

**feedstocks** / `bot-feedstocks.yml`: Updates the list of valid and archived feedstocks in `conda-forge` located at `cf-graph-countyfair/all_feedstocks.json`.

**versions** / `bot-versions.yml`: Fetches the latest version for each feedstock in `conda-forge`, writing the data to `cf-graph-countyfair/versions/`.

**prs** / `bot-prs.yml`: Fetches the latest PR statuses from GitHub for all of the PRs that bot has made, writing the data to`cf-graph-countyfair/pr_json`.

**pypi-mapping** / `bot-pypi-mapping.yml`: Builds a mapping of packages between PyPI and `conda-forge`, and a mapping of python imports to packages using the bot's metadata. The PyPI mapping is written to `cf-graph-countyfair/mappings` and the import mapping is written to `cf-graph-countyfair/import_to_pkg_maps`. This job also generates some internal data stored at `cf-graph-countyfair/ranked_hubs_authorities.json`.

**make-graph** / `bot-make-graph.yml`: Builds the `conda-forge` dependency graph from the feedstocks in `cf-graph-countyfair/all_feedstocks.json`. The graph is written to `cf-graph-countyfair/graph.json` and specific attributes for each node are written to `cf-graph-countyfair/node_attrs`. This job also performs some schema migrations and might add new files to `cf-graph-countyfair/pr_info` and `cf-graph-countyfair/version_pr_info`.

**make-migrators** / `bot-make-migrators.yml`: Builds the migrations the bot will run, writing them as JSON to `cf-graph-countyfair/migrators`.

**update-status-page** / `bot-update-status-page.yml`: Updates the status page at `conda-forge.org/status` with the latest migration information. The status data is written to `cf-graph-countyfair/status`.

**[NOT CURRENTLY USED] cache** / `bot-cache.yml`: Caches the data in `cf-graph-countyfair` to GitHub Actions.

**keepalive** / `bot-keepalive.yml`: This job runs every 15 minutes and ensures that the bot is still running. If the bot is not running, it will restart it.

Many of these jobs could be converted to a more event-driven model, especially the job that updates the status of PRs (**prs**) and the parts of the jobs that update attributes of the graph nodes (**make-graph**). However, there are some caveats. Even with event-driven updates, the bot would still need cron jobs for these tasks to ensure that data eventually gets updated if events are missed. Further, the main limit on the bot making PRs is the **bot** job itself. Making this job respond to events is a non-trivial task due to many reasons, including the fact that once a given a PR is merged on a feedstock, there is a few-hour delay before the next PR can be made.

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
this repository and hosted via `ghcr.io`. The `__version__` tag is used for production jobs and updated automatically
when PRs are merged. The container is typically run via

```bash
docker run --rm -t conda-forge-tick:<__version__> python /opt/autotick-bot/docker/run_bot_task.py <task> <args>
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
