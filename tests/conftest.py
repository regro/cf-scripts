import os

import pytest
from conda_forge_tick import global_sensitive_env


@pytest.fixture
def env_setup():
    old_pwd = os.environ.pop("PASSWORD", None)
    os.environ["PASSWORD"] = "unpassword"
    global_sensitive_env.hide_env_vars()
    yield
    global_sensitive_env.reveal_env_vars()
    if old_pwd:
        os.environ["PASSWORD"] = old_pwd
