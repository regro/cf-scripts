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
To define a test case, create a subclass of `tests_integration.lib.test_case.TestCase` in the `__init__.py` file of
your feedstock. You can name it arbitrarily.
Referring to the minimal `VersionUpdate` test case in the
[pydantic module](definitions/pydantic/__init__.py),
your class has to implement three methods:

1. `get_router()` should return an `APIRouter` object to define mock responses for specific HTTP requests. All web requests are intercepted by an HTTP proxy.
Refer to `tests_integration.lib.shared.get_transparent_urls` to define URLs that should not be intercepted.

2. `prepare(helper: IntegrationTestHelper)` for setting up your test case. Usually, you will want to
overwrite the feedstock repository in the test environment. The `IntegrationTestHelper` provides methods to interact
with the test environment.

3. A function `validate(helper: IntegrationTestHelper)` for validating the state after the bot has run.
The `IntegrationTestHelper` provides convenience methods such as `assert_version_pr_present` to check for the presence
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

The generation of test scenarios is done in [collect_test_scenarios.py](collect_test_scenarios.py). It is pseudo-random,
ensuring that faulty interactions between test cases are detected eventually.

In detail, the process of collecting test scenarios is as follows:

#### 1. Collect Test Cases
For each feedstock, collect the available test cases in lexically sorted order.

![
Table with two columns: "Feedstock A" and "Feedstock B". Feedstock A has 5 test cases: `test_case_1.py` to
`test_case_5.py`. Feedstock B has two test cases: `test_case_1.py` and `test_case_2.py`.
](../docs/assets/integration-tests/scenarios-definition-1-light.svg#gh-light-mode-only)
![Description available in light mode.](../docs/assets/integration-tests/scenarios-definition-1-dark.svg#gh-dark-mode-only)

#### 2. Fill Test Scenarios
The number of test scenarios is equal to the maximum number of test cases for a feedstock.
Feedstocks that have fewer test cases repeat their test cases to supply exactly one test case per scenario.
In the example below, the last instance of `test_case_2.py` for Feedstock B is not needed and thus discarded.

![
The same image as above, but the rows under Feedstock B are filled with the following alternating test cases: 1, 2, 1, 2, 1, 2.
The last instance of test case 2 is marked grey to indicate that it is not needed, because it overhangs as compared to Feedstock A.
](../docs/assets/integration-tests/scenarios-extension-2-light.svg#gh-light-mode-only)
![Description available in light mode.](../docs/assets/integration-tests/scenarios-extension-2-dark.svg#gh-dark-mode-only)

#### 3. Shuffle Test Scenarios
For each feedstock, we shuffle the test cases (rows) individually to ensure a random combination of test cases.
The shuffling is done pseudo-randomly based on `GITHUB_RUN_ID` (which persists for re-runs of the same workflow).

Finally, we get the test scenarios as the rows of the table below.
Each test scenario executes exactly one test case per feedstock, in parallel.

![
Feedstock A has the following test cases: 3, 1, 4, 2, 5 (shuffled).
Feedstock B has the following test cases: 2, 1, 1, 2, 1 (shuffled).
Each row represents a test scenario.
For example, scenario 1 uses `test_case_3.py` from Feedstock A and `test_case_2.py` from Feedstock B.
](../docs/assets/integration-tests/scenarios-shuffle-3-light.svg#gh-light-mode-only)
![Description available in light mode.](../docs/assets/integration-tests/scenarios-shuffle-3-dark.svg#gh-dark-mode-only)

## Environment Variables
The tests expect the following environment variables:

| Variable           | Description                                                                                                                       |
|--------------------|-----------------------------------------------------------------------------------------------------------------------------------|
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
