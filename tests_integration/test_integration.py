import contextlib
import logging
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests_integration import setup_repositories
from tests_integration.collect_test_scenarios import get_test_scenario
from tests_integration.lib.shared import setup_logging
from tests_integration.lib.test_case import TestCase
from tests_integration.step_prepare import (
    close_all_open_pull_requests,
    reset_cf_graph,
    run_all_prepare_functions,
)
from tests_integration.step_validate import run_all_validate_functions

TESTS_INTEGRATION_DIR = Path(__file__).parent


@pytest.fixture(scope="module", autouse=True)
def global_environment_setup():
    """
    Set up the global environment variables for the tests.
    If we once migrate to pydantic-settings, this should be more fine-grained for each bot step.
    """
    # assert os.environ.get("BOT_TOKEN"), "BOT_TOKEN must be set."
    assert os.environ.get("MITMPROXY_PEM"), "MITMPROXY_PEM must be set."
    assert os.environ.get("SSL_CERT_FILE"), "SSL_CERT_FILE must be set."
    assert os.environ.get("REQUESTS_CA_BUNDLE"), "REQUESTS_CA_BUNDLE must be set."
    assert os.environ.get("TEST_SETUP_TOKEN"), "TEST_SETUP_TOKEN must be set."

    # os.environ["CF_TICK_OVERRIDE_CONDA_FORGE_ORG"] = "conda-forge-bot-staging"
    # os.environ["CF_TICK_GRAPH_DATA_BACKENDS"] = "file"
    # os.environ["CF_FEEDSTOCK_OPS_CONTAINER_NAME"] = "conda-forge-tick"
    # os.environ["CF_FEEDSTOCK_OPS_CONTAINER_TAG"] = "test"
    # os.environ["CF_TICK_GRAPH_GITHUB_BACKEND_REPO"] = (
    #    "regro-staging/cf-graph-countyfair"
    # )
    # github_run_id = os.environ.get("GITHUB_RUN_ID", "GITHUB_RUN_ID_NOT_SET")
    # os.environ["RUN_URL"] = (
    #    f"https://github.com/regro/cf-scripts/actions/runs/{github_run_id}"
    # )

    # os.environ["CF_TICK_FRAC_MAKE_GRAPH"] = "1.0"

    setup_logging(logging.INFO)


@pytest.fixture(scope="module")
def repositories_setup():
    """
    Set up the repositories for the tests.
    """
    setup_repositories.prepare_all_accounts()


@pytest.fixture(params=[0])
def scenario(request) -> tuple[int, dict[str, TestCase]]:
    scenario_id: int = request.param
    close_all_open_pull_requests()
    reset_cf_graph()

    scenario = get_test_scenario(scenario_id)
    scenario_pretty_print = {
        feedstock_name: test_case.__class__.__name__
        for feedstock_name, test_case in scenario.items()
    }

    print(f"Preparing test scenario {scenario_id}...")
    print(f"Scenario: {scenario_pretty_print}")

    run_all_prepare_functions(scenario)

    return scenario_id, scenario


@pytest.fixture
def mitmproxy(scenario: tuple[int, dict[str, TestCase]]):
    scenario_id, _ = scenario
    print(f"Starting mitmproxy for scenario {scenario_id}...")

    proxy_process = subprocess.Popen(
        ["./mock_proxy_start.sh"], env=os.environ | {"SCENARIO_ID": str(scenario_id)}
    )
    yield
    proxy_process.kill()


@contextlib.contextmanager
def in_fresh_cf_graph():
    """
    Context manager to execute code within the context with a new clone
    of cf-graph in a temporary directory.
    """
    old_working_dir = os.getcwd()

    with tempfile.TemporaryDirectory() as tmpdir_s:
        tmpdir = Path(tmpdir_s)

        cf_graph_repo = os.environ["CF_TICK_GRAPH_GITHUB_BACKEND_REPO"]
        subprocess.run(
            [
                "git",
                "clone",
                "--depth=5",
                f"https://github.com/{cf_graph_repo}.git",
                "cf-graph",
            ],
            check=True,
            cwd=tmpdir,
        )

        cf_graph_dir = tmpdir / "cf-graph"

        subprocess.run(
            [
                "git",
                "config",
                "user.name",
                "regro-cf-autotick-bot-staging",
            ],
            check=True,
            cwd=cf_graph_dir,
        )

        subprocess.run(
            [
                "git",
                "config",
                "user.email",
                "regro-cf-autotick-bot-staging@users.noreply.github.com",
            ],
            check=True,
            cwd=cf_graph_dir,
        )

        subprocess.run(
            [
                "git",
                "config",
                "pull.rebase",
                "false",
            ],
            check=True,
            cwd=cf_graph_dir,
        )

        subprocess.run(["git", "config", 'http."https://github.com".proxy', '""'])  #

        os.chdir(cf_graph_dir)
        yield

    os.chdir(old_working_dir)


@contextlib.contextmanager
def mitmproxy_env():
    """
    Set environment variables for bot steps that should be piped through mitmproxy.
    """
    old_env = os.environ.copy()

    os.environ["http_proxy"] = "http://127.0.0.1:8080"
    os.environ["https_proxy"] = "http://127.0.0.1:8080"
    os.environ["CF_FEEDSTOCK_OPS_CONTAINER_PROXY_MODE"] = "true"

    # see https://github.com/conda-forge/conda-forge-feedstock-ops/blob/e9d52496b9df241a34b941ca5bfd2b52c1e019ed/conda_forge_feedstock_ops/container_utils.py#L23-L33
    if os.environ.get("GITHUB_ACTIONS"):
        os.environ["CF_FEEDSTOCK_OPS_PROXY_IN_CONTAINER"] = "http://172.17.0.1:8080"
    else:
        os.environ["CF_FEEDSTOCK_OPS_PROXY_IN_CONTAINER"] = (
            "http://host.docker.internal:8080"
        )

    yield

    os.environ = old_env


def invoke_bot_command(args: list[str]):
    """
    Invoke the bot command with the given arguments.
    """
    from conda_forge_tick import cli

    cli.main(args, standalone_mode=False)


# TODO: parameterize to include no containers test


@pytest.mark.integration
def test_scenario(
    scenario: tuple[int, dict[str, TestCase]], repositories_setup, mitmproxy
):
    _, scenario = scenario

    # import needs to happen dynamically because we set the environment variables first

    with in_fresh_cf_graph():
        invoke_bot_command(["--debug", "gather-all-feedstocks"])
        invoke_bot_command(["--debug", "deploy-to-github"])

    with in_fresh_cf_graph():
        invoke_bot_command(["--debug", "make-graph", "--update-nodes-and-edges"])
        invoke_bot_command(["--debug", "deploy-to-github"])

    with in_fresh_cf_graph():
        invoke_bot_command(["--debug", "make-graph"])
        invoke_bot_command(["--debug", "deploy-to-github"])

    with in_fresh_cf_graph(), mitmproxy_env():
        invoke_bot_command(["--debug", "update-upstream-versions"])
        invoke_bot_command(["--debug", "deploy-to-github"])

    with in_fresh_cf_graph(), mitmproxy_env():
        invoke_bot_command(["--debug", "make-migrators"])
        invoke_bot_command(["--debug", "deploy-to-github"])

    with in_fresh_cf_graph(), mitmproxy_env():
        invoke_bot_command(["--debug", "auto-tick"])
        invoke_bot_command(["--debug", "deploy-to-github"])

    with in_fresh_cf_graph(), mitmproxy_env():
        # because of an implementation detail in the bot, we need to run make-migrators twice
        # for changes to be picked up
        invoke_bot_command(["--debug", "make-migrators"])
        invoke_bot_command(["--debug", "deploy-to-github"])

    with in_fresh_cf_graph(), mitmproxy_env():
        # due to a similar implementation detail, we need to run auto-tick twice
        # for changes to be picked up
        invoke_bot_command(["--debug", "auto-tick"])
        invoke_bot_command(["--debug", "deploy-to-github"])

    run_all_validate_functions(scenario)
