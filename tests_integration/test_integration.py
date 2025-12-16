"""
Pytest entry point for the integration tests.
Please refer to the README.md in the tests_integration (i.e., parent) directory
for more information.
"""

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
from tests_integration.lib import (
    TestCase,
    close_all_open_pull_requests,
    get_all_test_scenario_ids,
    get_test_scenario,
    prepare_all_accounts,
    reset_cf_graph,
    run_all_prepare_functions,
    run_all_validate_functions,
    setup_logging,
)

from .lib._definitions import GitHubAccount

TESTS_INTEGRATION_DIR = Path(__file__).parent
CF_SCRIPTS_ROOT_DIR = TESTS_INTEGRATION_DIR.parent
MITMPROXY_CONFDIR = TESTS_INTEGRATION_DIR / ".mitmproxy"
MITMPROXY_CERT_BUNDLE_FILE = MITMPROXY_CONFDIR / "mitmproxy-cert-bundle.pem"


@pytest.fixture(scope="module", autouse=True)
def global_environment_setup():
    """Set up the global environment variables for the tests."""
    # Make sure to also set BOT_TOKEN, we cannot validate this here!
    assert os.environ.get("TEST_SETUP_TOKEN"), "TEST_SETUP_TOKEN must be set."

    # In Python 3.13, this might break. https://stackoverflow.com/a/79124282
    os.environ["MITMPROXY_CONFDIR"] = str(MITMPROXY_CONFDIR.resolve())
    os.environ["SSL_CERT_FILE"] = str(MITMPROXY_CERT_BUNDLE_FILE.resolve())
    os.environ["REQUESTS_CA_BUNDLE"] = str(MITMPROXY_CERT_BUNDLE_FILE.resolve())
    os.environ["GIT_SSL_CAINFO"] = str(MITMPROXY_CERT_BUNDLE_FILE.resolve())

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
    new_settings.graph_github_backend_repo = (
        f"{GitHubAccount.REGRO_ORG}/cf-graph-countyfair"
    )
    new_settings.conda_forge_org = GitHubAccount.CONDA_FORGE_ORG

    with use_settings(new_settings):
        setup_logging(logging.INFO)
        yield


@pytest.fixture
def disable_container_mode(monkeypatch):
    """Disable container mode for the test."""
    monkeypatch.setenv("CF_FEEDSTOCK_OPS_IN_CONTAINER", "true")


@pytest.fixture(scope="module")
def repositories_setup():
    """Set up the repositories for the tests."""
    prepare_all_accounts()


@pytest.fixture(params=get_all_test_scenario_ids())
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
    """Return if the proxy is running on localhost:port.

    Parameters
    ----------
    port
        The port to check.
    timeout
        The timeout in seconds.

    Returns
    -------
    bool
        True if the proxy is running, False otherwise.
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

        # --depth=5 is the same value as used in prod (see autotick-bot/install_bot_code.sh)
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

        subprocess.run(
            ["git", "config", 'http."https://github.com".proxy', '""'],
            check=True,
            cwd=cf_graph_dir,
        )

        os.chdir(cf_graph_dir)
        yield

    os.chdir(old_working_dir)


@contextlib.contextmanager
def mitmproxy_env():
    """Set environment variables for bot steps that should be piped through mitmproxy."""
    old_env = os.environ.copy()

    os.environ["http_proxy"] = "http://127.0.0.1:8080"
    os.environ["https_proxy"] = "http://127.0.0.1:8080"
    os.environ["CF_FEEDSTOCK_OPS_CONTAINER_PROXY_MODE"] = "true"

    yield

    os.environ.clear()
    os.environ.update(old_env)


def invoke_bot_command(args: list[str]):
    """Invoke the bot command with the given arguments."""
    from conda_forge_tick import cli

    cli.main(args, standalone_mode=False)


@pytest.mark.parametrize("use_containers", [False])  # FIXME - put this back, True])
def test_scenario(
    use_containers: bool,
    scenario: tuple[int, dict[str, TestCase]],
    repositories_setup,
    mitmproxy,
    request: pytest.FixtureRequest,
):
    """
    Execute the test scenario given by the scenario fixture (note that the fixture is
    parameterized, and therefore we run this for all scenarios).
    All steps of the bot are executed in sequence to test its end-to-end functionality.

    A test scenario assigns one test case to each feedstock. For details on
    the testing setup, please refer to the README.md in the tests_integration
    (i.e., parent) directory.

    Parameters
    ----------
    use_containers
        Whether container mode is enabled or not.
    scenario
        The test scenario to run. This is a tuple of (scenario_id, scenario),
        where scenario is a dictionary with the feedstock name as key and the test
        case name as value.
    repositories_setup
        The fixture that sets up the repositories.
    mitmproxy
        The fixture that sets up the mitmproxy.
    request
        The pytest fixture request object.
    """
    _, scenario = scenario

    if not use_containers:
        request.getfixturevalue("disable_container_mode")

    with in_fresh_cf_graph():
        invoke_bot_command(["--debug", "gather-all-feedstocks"])
        invoke_bot_command(["--debug", "deploy-to-github", "--git-only"])

    with in_fresh_cf_graph():
        invoke_bot_command(["--debug", "make-graph", "--update-nodes-and-edges"])
        invoke_bot_command(["--debug", "deploy-to-github", "--git-only"])

    with in_fresh_cf_graph():
        invoke_bot_command(["--debug", "make-graph"])
        invoke_bot_command(["--debug", "deploy-to-github", "--git-only"])

    with in_fresh_cf_graph():
        with mitmproxy_env():
            invoke_bot_command(["--debug", "update-upstream-versions"])
        invoke_bot_command(["--debug", "deploy-to-github", "--git-only"])

    with in_fresh_cf_graph():
        with mitmproxy_env():
            invoke_bot_command(["--debug", "make-migrators"])
        invoke_bot_command(["--debug", "deploy-to-github", "--git-only"])

    with in_fresh_cf_graph():
        with mitmproxy_env():
            invoke_bot_command(["--debug", "auto-tick"])
        invoke_bot_command(["--debug", "deploy-to-github", "--git-only"])

    with in_fresh_cf_graph():
        # because of an implementation detail in the bot, we need to run make-migrators twice
        # for changes to be picked up
        with mitmproxy_env():
            invoke_bot_command(["--debug", "make-migrators"])
        invoke_bot_command(["--debug", "deploy-to-github", "--git-only"])

    with in_fresh_cf_graph():
        # due to a similar implementation detail, we need to run auto-tick twice
        # for changes to be picked up
        with mitmproxy_env():
            invoke_bot_command(["--debug", "auto-tick"])
        invoke_bot_command(["--debug", "deploy-to-github", "--git-only"])

    run_all_validate_functions(scenario)
