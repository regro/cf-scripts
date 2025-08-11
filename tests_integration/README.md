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
The integration tests are defined in the [lib/_definitions](lib/_definitions) directory. The following directory structure is
used (using `pydantic` and `llvmdev` as example feedstocks):

```text
definitions/
├── pydantic/
│   ├── resources/
│   │   ├── feedstock
│   │   └── ... (entirely custom)
│   └── __init__.py
├── llvmdev/
│   ├── resources/
│   └── __init__.py
└── ...
```

Each feedstock has its own Python module containing the test cases for that feedstock.
**The test cases are always defined in the top-level `__init__.py` file of the feedstock directory.**

For storing resources, a `resources` directory is used for each feedstock directory.
Inside the `resources` directory, you can use an arbitrary directory structure to store the resources.

Usually, we include a specific revision of the original feedstock as a submodule in the `resources` directory.

A test case always tests the entire pipeline of the bot and not any intermediate states that could be checked
in the cf-graph. See the [pytest test definition](test_integration.py) for more details.
Also, a test case is always bound to one specific feedstock.

### Test Case Definition
To define a test case, create a subclass of `tests_integration.lib.TestCase` in the `__init__.py` file of
your feedstock. You can name it arbitrarily.
Referring to the minimal `VersionUpdate` test case in the
[pydantic module](lib/_definitions/pydantic/__init__.py),
your class has to implement three methods:

1. `get_router()` should return an `APIRouter` object to define mock responses for specific HTTP requests. All web requests are intercepted by an HTTP proxy.
Refer to `tests_integration.lib.get_transparent_urls` to define URLs that should not be intercepted.

2. `prepare(helper: AbstractIntegrationTestHelper)` for setting up your test case. Usually, you will want to
overwrite the feedstock repository in the test environment. The `AbstractIntegrationTestHelper` provides methods to interact
with the test environment.

3. A function `validate(helper: AbstractIntegrationTestHelper)` for validating the state after the bot has run.
The `AbstractIntegrationTestHelper` provides convenience methods such as `assert_version_pr_present` to check for the presence
of a version update PR.

The creation of GitHub repositories in the test environment is done automatically based on the directory structure.

### Adding to Test Case Lists

> [!IMPORTANT]
> Please make sure to add any added test cases to the `ALL_TEST_CASES` list in the respective `__init__.py` file of the feedstock.
> You also need to add any added feedstock to the `TEST_CASE_MAPPING` dictionary in the `definitions/__init__.py` file.

### How Test Cases are Run

Importantly, the integration test workflow does not execute the test cases directly.
Instead, it groups them into test scenarios and executes those at once.
A test scenario assigns one test case to every feedstock and runs them in parallel.

Thus, test cases of different feedstocks can run simultaneously, but the different test cases for the same feedstock
are always run sequentially.

The generation of test scenarios is done in [_collect_test_scenarios.py](lib/_collect_test_scenarios.py). It is pseudo-random,
ensuring that faulty interactions between test cases are detected eventually.

In detail, the process of collecting test scenarios is as follows:

#### 1. Collect Test Cases
For each feedstock, collect the available test cases in lexically sorted order.

| Feedstock A | Feedstock B |
|-------------|-------------|
| Test Case 1 | Test Case 1 |
| Test Case 2 | Test Case 2 |
| Test Case 3 |             |
| Test Case 4 |             |
| Test Case 5 |             |


#### 2. Fill Test Scenarios
The number of test scenarios is equal to the maximum number of test cases for a feedstock.
Feedstocks that have fewer test cases repeat their test cases to supply exactly one test case per scenario.
In the example below, the last instance of `test_case_2.py` for Feedstock B is not needed and thus discarded.


| Feedstock A                  | Feedstock B                  |
|------------------------------|------------------------------|
| Test Case 1                  | Test Case 1                  |
| Test Case 2                  | Test Case 2                  |
| Test Case 3                  | Test Case 1                  |
| Test Case 4                  | Test Case 2                  |
| Test Case 5                  | Test Case 1                  |
| ✂️ everything is cut here ✂️ | ✂️ everything is cut here ✂️ |
|                              | Test Case 2 (discarded 🗑️)  |

#### 3. Shuffle Test Scenarios
For each feedstock, we shuffle the test cases (rows) individually to ensure a random combination of test cases.
The shuffling is done pseudo-randomly based on `GITHUB_RUN_ID` (which persists for re-runs of the same workflow).

Finally, we get the test scenarios as the rows of the table below.
Each test scenario executes exactly one test case per feedstock, in parallel.

|            | Feedstock A | Feedstock B |
|------------|-------------|-------------|
| Scenario 1 | Test Case 3 | Test Case 2 |
| Scenario 2 | Test Case 1 | Test Case 1 |
| Scenario 3 | Test Case 4 | Test Case 1 |
| Scenario 4 | Test Case 2 | Test Case 2 |
| Scenario 5 | Test Case 5 | Test Case 1 |


## Environment Variables
The tests expect the following environment variables:

| Variable           | Description                                                                                                                       |
|--------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| `GITHUB_ACCOUNT_CONDA_FORGE_ORG` | The GitHub organization mimicking `conda-forge`. Defaults to `conda-forge-bot-staging`.                      |
| `GITHUB_ACCOUNT_REGRO_ORG` | The GitHub organization mimicking [regro](https://github.com/regro). Defaults to `regro-staging`.  |
| `GITHUB_ACCOUNT_BOT_USER` | The GitHub user to interact with `$GITHUB_ACCOUNT_CONDA_FORGE_ORG` and `$GITHUB_ACCOUNT_REGRO_ORG`. Defaults to `regro-cf-autotick-bot-staging`.  |
| `BOT_TOKEN`        | Classic PAT for `cf-regro-autotick-bot-staging`. Used to interact with the test environment.                                      |
| `TEST_SETUP_TOKEN` | Classic PAT for `cf-regro-autotick-bot-staging` used to setup the test environment. Typically, this is identical to `BOT_TOKEN`.  |
| `GITHUB_RUN_ID`    | Set by GitHub. ID of the current run. Used as random seed.                                                                        |


We do not use `BOT_TOKEN` instead of `TEST_SETUP_TOKEN` for setting up the test environment to allow for future separation of the two tokens.
Furthermore, `BOT_TOKEN` is hidden by the sensitive env logic of `conda_forge_tick` and we want the test environment to not need to rely on this logic.


### GitHub Token Permissions
The bot token (which you can should use as the test setup token) should have the following scopes: `repo`, `workflow`, `delete_repo`.

## Running the Integration Tests Locally

To run the integration tests locally, you currently need to have a valid token for the `cf-regro-autotick-bot-staging` account.
Besides that, run the following setup wizard to set up self-signed certificates for the HTTP proxy:

```bash
./mitmproxy_setup_wizard.sh
```

After that, run the following command to run the tests
(you need to be in the `tests_integration` directory):

```bash
pytest -s -v --dist=no tests_integration
```

Remember to set the environment variables from above beforehand.

## Debugging CI Issues

The proxy setup of the integration tests is quite complex, and you can experience issues that only occur on GitHub Actions
and not locally.

To debug them, consider to [use vscode-server-action](https://gist.github.com/ytausch/612106cfbc2cc660130d247fa2f3a673).
