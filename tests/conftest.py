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
def set_cf_tick_container_tag_to_test():
    old_cftct = os.environ.get("CF_TICK_CONTAINER_TAG")
    if old_cftct is None:
        os.environ["CF_TICK_CONTAINER_TAG"] = "test"

    yield

    if old_cftct is None:
        del os.environ["CF_TICK_CONTAINER_TAG"]
    else:
        os.environ["CF_TICK_CONTAINER_TAG"] = old_cftct


@pytest.fixture(autouse=True, scope="session")
def set_cf_tick_container_name_to_local():
    old_cftcn = os.environ.get("CF_TICK_CONTAINER_NAME")
    if old_cftcn is None:
        os.environ["CF_TICK_CONTAINER_NAME"] = "conda-forge-tick"

    yield

    if old_cftcn is None:
        del os.environ["CF_TICK_CONTAINER_NAME"]
    else:
        os.environ["CF_TICK_CONTAINER_NAME"] = old_cftcn


@pytest.fixture(autouse=True, scope="session")
def turn_off_containers_by_default():
    old_in_container = os.environ.get("CF_TICK_IN_CONTAINER")

    # tell the code we are in a container so that it
    # doesn't try to run docker commands
    os.environ["CF_TICK_IN_CONTAINER"] = "true"

    yield

    if old_in_container is None:
        os.environ.pop("CF_TICK_IN_CONTAINER", None)
    else:
        os.environ["CF_TICK_IN_CONTAINER"] = old_in_container


@pytest.fixture
def use_containers():
    old_in_container = os.environ.get("CF_TICK_IN_CONTAINER")

    os.environ["CF_TICK_IN_CONTAINER"] = "false"

    yield

    if old_in_container is None:
        os.environ.pop("CF_TICK_IN_CONTAINER", None)
    else:
        os.environ["CF_TICK_IN_CONTAINER"] = old_in_container
