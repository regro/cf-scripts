# Integration Tests
This directory contains integration tests for the autotick-bot.
The tests are run against actual GitHub repositories, and are used to verify that the
bot works as expected in an environment closely resembling production.

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

## Structure of the Test Case Definitions
Inside the `definitions` module, each feedstock that is part of the test suite has its own
submodule.
