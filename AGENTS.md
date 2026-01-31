# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project Overview

This is **autotick-bot** (conda-forge-tick), the automated maintenance bot for the conda-forge ecosystem. It creates PRs to update packages, run migrations, and maintain the conda-forge dependency graph across thousands of feedstocks.

## Common Commands

### Development Setup
```bash
# Using environment.yml
conda env create -f environment.yml

# Or using the lockfile
conda-lock install conda-lock.yml

# Install in editable mode
pip install -e .
```

### Running Tests
```bash
# Run all tests (requires docker for container tests)
pytest -v

# Run tests in parallel
pytest -v -n 3

# Run a single test
pytest -v tests/test_file.py::test_function

# Skip MongoDB tests
pytest -v -m "not mongodb"

# To enable container-based tests, first build the test image:
docker build -t conda-forge-tick:test .
```

### CLI Usage
```bash
# General help
conda-forge-tick --help

# Debug mode (enables debug logging, disables multiprocessing)
conda-forge-tick --debug <command>

# Online mode (fetches graph data from GitHub, useful for local testing)
conda-forge-tick --online <command>

# Disable containers (for debugging, but note security implications)
conda-forge-tick --no-containers <command>

# Example: update upstream versions for a single package
conda-forge-tick --debug --online update-upstream-versions numpy
```

### Linting
```bash
# Pre-commit handles linting (ruff, mypy, typos)
pre-commit run --all-files
```

## Architecture

### Core Components

**CLI Entry Points** (`conda_forge_tick/cli.py`, `conda_forge_tick/container_cli.py`):
- `conda-forge-tick`: Main CLI for bot operations
- `conda-forge-tick-container`: CLI for containerized operations

**Key Modules**:
- `auto_tick.py`: Main bot job - creates PRs for migrations and version updates
- `make_graph.py`: Builds the conda-forge dependency graph
- `make_migrators.py`: Initializes migration objects
- `update_upstream_versions.py`: Fetches latest versions from upstream sources
- `update_prs.py`: Updates PR statuses from GitHub
- `feedstock_parser.py`: Parses feedstock metadata

### Migrators (`conda_forge_tick/migrators/`)

Base class: `Migration` in `core.py`. Migrators handle automated changes:
- `version.py`: Version updates (special - uses `CondaMetaYAML` parser)
- `migration_yaml.py`: CFEP-09 YAML migrations from conda-forge-pinning
- `arch.py`, `cross_compile.py`: Architecture migrations
- Custom migrators for specific ecosystem changes (libboost, numpy2, etc.)

### Data Model

The bot uses `cf-graph-countyfair` repository as its database. Key structures:
- `graph.json`: NetworkX dependency graph
- `node_attrs/`: Package metadata (one JSON per package, sharded paths)
- `versions/`: Upstream version information
- `pr_json/`: PR status tracking
- `pr_info/`, `version_pr_info/`: Migration/version PR metadata

Pydantic models in `conda_forge_tick/models/` document the schema.

### LazyJson System

Data is loaded lazily via `LazyJson` class. Backends configured via `CF_TICK_GRAPH_DATA_BACKENDS`:
- `file`: Local filesystem (default, requires cf-graph-countyfair clone)
- `github`: Read-only from GitHub raw URLs (good for debugging)
- `mongodb`: MongoDB database

### Recipe Parsing

`CondaMetaYAML` in `recipe_parser/` handles Jinja2-templated YAML recipes:
- Preserves comments (important for conda selectors)
- Handles duplicate keys with different selectors via `__###conda-selector###__` tokens
- Extracts Jinja2 variables for version migration

## Environment Variables

See `conda_forge_tick/settings.py` for full list. Key ones:
- `CF_TICK_GRAPH_DATA_BACKENDS`: Colon-separated backend list
- `CF_TICK_GRAPH_DATA_USE_FILE_CACHE`: Enable/disable local caching
- `MONGODB_CONNECTION_STRING`: MongoDB connection string
- `BOT_TOKEN`: GitHub token for bot operations
- `CF_FEEDSTOCK_OPS_IN_CONTAINER`: Set to "true" when running in container

## Bot Jobs Structure

The bot runs as multiple parallel cron jobs via GitHub Actions:
- `bot-bot.yml`: Main job making PRs
- `bot-feedstocks.yml`: Updates feedstock list
- `bot-versions.yml`: Fetches upstream versions
- `bot-prs.yml`: Updates PR statuses
- `bot-make-graph.yml`: Builds dependency graph
- `bot-make-migrators.yml`: Creates migration objects
- `bot-pypi-mapping.yml`: PyPI to conda-forge mapping

## Integration Tests

Located in `tests_integration/`. Tests the full bot pipeline against real GitHub repositories using staging accounts.

### Test Environment Architecture

The integration tests require three GitHub entities that mimic production:
- **Conda-forge org** (`GITHUB_ACCOUNT_CONDA_FORGE_ORG`): Contains test feedstocks
- **Bot user** (`GITHUB_ACCOUNT_BOT_USER`): Creates forks and PRs
- **Regro org** (`GITHUB_ACCOUNT_REGRO_ORG`): Contains a test `cf-graph-countyfair` repository

Default staging accounts are `conda-forge-bot-staging`, `regro-cf-autotick-bot-staging`, and `regro-staging`. You can use your own accounts by setting environment variables.

### Setup

1. **Initialize git submodules** (test feedstock resources are stored as submodules):
```bash
git submodule update --init --recursive
```

2. **Create a `.env` file** with required environment variables:
```bash
export BOT_TOKEN='<github-classic-pat>'
export TEST_SETUP_TOKEN='<github-classic-pat>'  # typically same as BOT_TOKEN
export GITHUB_ACCOUNT_CONDA_FORGE_ORG='your-conda-forge-staging-org'
export GITHUB_ACCOUNT_BOT_USER='your-bot-user'
export GITHUB_ACCOUNT_REGRO_ORG='your-regro-staging-org'
export PROXY_DEBUG_LOGGING='true'  # optional, for debugging
```

GitHub token requires scopes: `repo`, `workflow`, `delete_repo`.

3. **Set up mitmproxy certificates** (required for HTTP proxy that intercepts requests):
```bash
cd tests_integration
./mitmproxy_setup_wizard.sh
```

On macOS: Add the generated certificate to Keychain Access and set "Always Trust".
On Linux: Copy to `/usr/local/share/ca-certificates/` and run `update-ca-certificates`.

4. **Build the Docker test image** (required for container-based tests):
```bash
docker build -t conda-forge-tick:test .
```

### Running Integration Tests

**Important**: Integration tests take a long time to execute (5+ minutes per test). To avoid repeated runs:
- Persist stdout/stderr to a file and grep for errors
- Run tests in the background while working on other tasks

```bash
# Source your environment variables
source .env

# Run from repository root, skipping container tests (default)
# Recommended: redirect output to file for later analysis
pytest -s -v --dist=no tests_integration -k "False" > /tmp/integration_test.log 2>&1 &
tail -f /tmp/integration_test.log  # follow output in another terminal

# Or run interactively if needed
pytest -s -v --dist=no tests_integration -k "False"

# Run only container tests (requires Docker image built with test tag)
pytest -s -v --dist=no tests_integration -k "True"

# Run a specific test scenario
pytest -s -v --dist=no tests_integration -k "test_scenario[0]"
```

### Test Case Structure

Test cases are defined in `tests_integration/lib/_definitions/<feedstock>/__init__.py`. Each test case:
1. `get_router()`: Defines mock HTTP responses via FastAPI router
2. `prepare(helper)`: Sets up test state (e.g., overwrites feedstock contents)
3. `validate(helper)`: Asserts expected outcomes (e.g., PR was created with correct changes)

### How Tests Execute

Tests run the full bot pipeline in sequence:
1. `gather-all-feedstocks`
2. `make-graph --update-nodes-and-edges`
3. `make-graph`
4. `update-upstream-versions`
5. `make-migrators`
6. `auto-tick`
7. (repeat migrators and auto-tick for state propagation)

Each step deploys to the staging `cf-graph-countyfair` repo.
