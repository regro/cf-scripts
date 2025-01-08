# Integration Tests
This directory contains integration tests for the autotick-bot.
The tests are run against actual GitHub repositories, and are used to verify that the
bot works as expected in an environment closely resembling production.

## Test Environment
The integration tests operate in a testing environment consisting of three real GitHub entities:

- [conda-forge-bot-staging](https://github.com/conda-forge-bot-staging) (organization) mimics the
[conda-forge](https://github.com/conda-forge) organization and will contain a selection of test feedstocks
(see below how we create them)
- [regro-cf-autotick-bot-staging](https://github.com/regro-cf-autotick-bot-staging) (user) mimics the
[regro-cf-autotick-bot](https://github.com/regro-cf-autotick-bot) account and is a test environment in which the bot
will create forks of the conda-forge-bot-staging repositories
- [regro-staging](https://github.com/regro-staging) (organization) (named after the [regro](https://github.com/regro)
account) contains a special version of the [cf-graph-countyfair](https://github.com/regro/cf-graph-countyfair) which
the bot uses during testing.

## Test Cases Definition
The integration tests are defined in the [definitions](definitions) directory. The following directory structure is
used (using `pydantic` and `llvmdev` as example feedstocks):

```text
definitions/
├── pydantic/
│   ├── resources/
│   │   ├── feedstock
│   │   └── ... (entirely custom)
│   ├── version_update.py
│   ├── aarch_migration.py
│   ├── some_other_test_case.py
│   └── ...
├── llvmdev/
│   ├── resources/
│   └── test_case.py
└── ...
```

Each feedstock has its own directory containing the test cases for that feedstock. The test cases are defined in
Python files in the feedstock directory, where each file contains a single test case.

For storing resources, a `resources` directory is used for each feedstock directory.
Inside the `resources` directory, you can use an arbitrary directory structure to store the resources.

Usually, we include a specific revision of the original feedstock as a submodule in the `resources` directory.

A test case always tests the entire pipeline of the bot and not any intermediate states that could be checked
in the cf-graph. See the [workflow file](../.github/workflows/test-integration.yml) for more details.
Also, a test case is always bound to one specific feedstock.

### Test Case Definition
To define a test case, create a Python file in the definitions dir of the feedstock. Referring to
[this](definitions/pydantic/version_update.py) minimal test case,
you have to define three things:

1. A function `prepare(helper: IntegrationTestHelper)` for setting up your test case. Usually, you will want to
overwrite the feedstock repository in the test environment. The `IntegrationTestHelper` provides methods to interact
with the test environment.

2. A `router` object to define mock responses for specific HTTP requests. All web requests are intercepted by an HTTP proxy.
Consult `tests_integration.lib.shared.TRANSPARENT_URLS` to define URLs that should not be intercepted.

3. A function `validate(helper: IntegrationTestHelper)` for validating the state after the bot has run.
The `IntegrationTestHelper` provides convenience methods such as `assert_version_pr_present` to check for the presence
of a version update PR.

The creation of GitHub repositories in the test environment is done automatically based on the directory structure.

### How Test Cases are Run

Importantly, the integration test workflow does not execute the test cases directly.
Instead, it groups them into test scenarios and executes those at once.
A test scenario is a mapping from feedstocks to a specific test case for that feedstock.

Thus, test cases of different feedstocks can run simultaneously, but the different test cases for the same feedstock
are always run sequentially.

The generation of test scenarios is done in [collect_test_scenarios.py](collect_test_scenarios.py). It is pseudo-random,
ensuring that faulty interactions between test cases are detected eventually.

## Environment Variables
The tests require the following environment variables to be set:

| Variable           | Description                                                                                                                      |
|--------------------|----------------------------------------------------------------------------------------------------------------------------------|
| `TEST_SETUP_TOKEN` | Classic PAT for `cf-regro-autotick-bot-staging` used to setup the test environment. Typically, this is identical to `BOT_TOKEN`. |
| `GITHUB_OUTPUT`    | Set by GitHub. Name of an output file for script outputs.                                                                        |
| `GITHUB_RUN_ID`    | Set by GitHub. ID of the current run. Used as random seed.                                                                       |


We do not use `BOT_TOKEN` instead of `TEST_SETUP_TOKEN` for setting up the test environment to allow for future separation of the two tokens.
Furthermore, `BOT_TOKEN` is hidden by the sensitive env logic of `conda_forge_tick` and we want the test environment to not need to rely on this logic.


### GitHub Token Permissions
The token should have the following scopes: `repo`, `workflow`, `delete_repo`.
