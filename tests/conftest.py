import os

import pytest

from conda_forge_tick import global_sensitive_env


@pytest.fixture
def env_setup():
    if "TEST_BOT_TOKEN_VAL" not in os.environ:
        old_pwd = os.environ.pop("BOT_TOKEN", None)
        os.environ["BOT_TOKEN"] = "unpassword"
        global_sensitive_env.hide_env_vars()

    old_pwd2 = os.environ.pop("pwd", None)
    os.environ["pwd"] = "pwd"

    yield

    if "TEST_BOT_TOKEN_VAL" not in os.environ:
        global_sensitive_env.reveal_env_vars()
        if old_pwd:
            os.environ["BOT_TOKEN"] = old_pwd

    if old_pwd2:
        os.environ["pwd"] = old_pwd2


@pytest.fixture(autouse=True, scope="session")
def set_cf_tick_pytest_envvar():
    old_ci = os.environ.get("CF_TICK_PYTEST")
    if old_ci is None:
        os.environ["CF_TICK_PYTEST"] = "true"
    yield
    if old_ci is None:
        del os.environ["CF_TICK_PYTEST"]
    else:
        os.environ["CF_TICK_PYTEST"] = old_ci
