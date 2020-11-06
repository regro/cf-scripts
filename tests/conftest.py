import os

import pytest
from conda_forge_tick import global_sensitive_env


@pytest.fixture
def env_setup():

    if "TEST_PASSWORD_VAL" not in os.environ:
        old_pwd = os.environ.pop("PASSWORD", None)
        os.environ["PASSWORD"] = "unpassword"
        global_sensitive_env.hide_env_vars()

    old_pwd2 = os.environ.pop("pwd", None)
    os.environ["pwd"] = "pwd"

    yield

    if "TEST_PASSWORD_VAL" not in os.environ:
        global_sensitive_env.reveal_env_vars()
        if old_pwd:
            os.environ["PASSWORD"] = old_pwd

    if old_pwd2:
        os.environ["pwd"] = old_pwd2
