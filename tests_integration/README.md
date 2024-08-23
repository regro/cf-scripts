# Integration Tests
This directory contains integration tests for the autotick-bot.
The tests are run against actual GitHub repositories, and are used to verify that the
bot works as expected in an environment closely resembling production.

## Environment Variables
The tests require the following environment variables to be set:

| Variable                       | Description                                                                                    |
|--------------------------------|------------------------------------------------------------------------------------------------|
| `GH_TOKEN_STAGING_CONDA_FORGE` | Personal Access Token (PAT) for the `conda-forge-bot-staging` GitHub organization (see below). |
| `GH_TOKEN_STAGING_BOT_USER`    | PAT for `cf-regro-autotick-bot-staging` GitHub user (see below).                               |
| `GH_TOKEN_STAGING_REGRO`       | PAT for the `regro-staging` GitHub organization (see below).                                   |
| `GITHUB_OUTPUT`                | Set by GitHub. Name of an output file for script outputs.                                      |
| `GITHUB_RUN_ID`                | Set by GitHub. ID of the current run. Used as random seed.                                     |


### GitHub Token Permissions
All tokens should have the following permissions:

**Repository Access:** All repositories.

**Repository Permissions:**
- Actions: read and write
- Administration: read and write
- Contents: read and write
- Metadata: read-only
- Pull requests: read and write
- Workflows: read and write

**Organization Permissions:** None.

## Structure of the Test Case Definitions
Inside the `definitions` module, each feedstock that is part of the test suite has its own
submodule.
