import contextlib
import logging
import os
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest
from xprocess import ProcessStarter, XProcess

from conda_forge_tick.settings import settings, use_settings
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
CF_SCRIPTS_ROOT_DIR = TESTS_INTEGRATION_DIR.parent
MITMPROXY_CONFDIR = TESTS_INTEGRATION_DIR / ".mitmproxy"
MITMPROXY_CERT_BUNDLE_FILE = MITMPROXY_CONFDIR / "mitmproxy-cert-bundle.pem"


@pytest.fixture(scope="module", autouse=True)
def global_environment_setup():
    """
    Set up the global environment variables for the tests.
    If we once migrate to pydantic-settings, this should be more fine-grained for each bot step.
    """
    # Make sure to also set BOT_TOKEN, we cannot validate this here!
    assert os.environ.get("TEST_SETUP_TOKEN"), "TEST_SETUP_TOKEN must be set."

    os.environ["MITMPROXY_CONFDIR"] = str(MITMPROXY_CONFDIR.resolve())
    os.environ["SSL_CERT_FILE"] = str(MITMPROXY_CERT_BUNDLE_FILE.resolve())
    os.environ["REQUESTS_CA_BUNDLE"] = str(MITMPROXY_CERT_BUNDLE_FILE.resolve())

    github_run_id = os.environ.get("GITHUB_RUN_ID", "GITHUB_RUN_ID_NOT_SET")
    os.environ["RUN_URL"] = (
        f"https://github.com/regro/cf-scripts/actions/runs/{github_run_id}"
    )

    # by default, we enable container mode because it is the default in the bot
    os.environ["CF_FEEDSTOCK_OPS_IN_CONTAINER"] = "false"

    # set if not set
    os.environ.setdefault("CF_FEEDSTOCK_OPS_CONTAINER_NAME", "conda-forge-tick")
    os.environ.setdefault("CF_FEEDSTOCK_OPS_CONTAINER_TAG", "test")

    new_settings = settings()

    new_settings.frac_make_graph = 1.0  # do not skip nodes due to randomness
    new_settings.frac_update_upstream_versions = 1.0
    new_settings.graph_github_backend_repo = "regro-staging/cf-graph-countyfair"
    new_settings.conda_forge_org = "conda-forge-bot-staging"

    use_settings(new_settings)
    setup_logging(logging.INFO)

    yield

    # reset settings
    use_settings(None)


@pytest.fixture
def disable_container_mode():
    """
    Disable container mode for the test.
    """
    value_before = os.environ["CF_FEEDSTOCK_OPS_IN_CONTAINER"]
    os.environ["CF_FEEDSTOCK_OPS_IN_CONTAINER"] = "true"
    yield
    os.environ["CF_FEEDSTOCK_OPS_IN_CONTAINER"] = value_before


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


def is_proxy_running(port: int, timeout: float = 2.0) -> bool:
    """
    Returns if the proxy is running on localhost:port.

    :param port: The port to check.
    :param timeout: The timeout in seconds.

    :return: A function that returns True if the proxy is running, False otherwise.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex(("localhost", port)) == 0


@pytest.fixture
def mitmproxy(xprocess: XProcess, scenario: tuple[int, dict[str, TestCase]]):
    scenario_id, _ = scenario

    class MitmproxyStarter(ProcessStarter):
        args = ["./mock_proxy_start.sh"]
        timeout = 60
        popen_kwargs = {"cwd": TESTS_INTEGRATION_DIR}
        env = os.environ | {
            "SCENARIO_ID": str(scenario_id),
            "PYTHONPATH": str(CF_SCRIPTS_ROOT_DIR.resolve()),
        }

        def startup_check(self):
            return is_proxy_running(port=8080)

    xprocess.ensure("mitmproxy", MitmproxyStarter)

    yield

    xprocess.getinfo("mitmproxy").terminate()


@contextlib.contextmanager
def in_fresh_cf_graph():
    """
    Context manager to execute code within the context with a new clone
    of cf-graph in a temporary directory.
    """
    old_working_dir = os.getcwd()

    with tempfile.TemporaryDirectory() as tmpdir_s:
        tmpdir = Path(tmpdir_s)

        cf_graph_repo = settings().graph_github_backend_repo
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

    yield

    os.environ = old_env


def invoke_bot_command(args: list[str]):
    """
    Invoke the bot command with the given arguments.
    """
    from conda_forge_tick import cli

    cli.main(args, standalone_mode=False)


@pytest.mark.parametrize("use_containers", [False, True])
def test_scenario(
    use_containers: bool,
    scenario: tuple[int, dict[str, TestCase]],
    repositories_setup,
    mitmproxy,
    request: pytest.FixtureRequest,
):
    _, scenario = scenario

    if not use_containers:
        request.getfixturevalue("disable_container_mode")

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
