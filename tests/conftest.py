import os

import pytest
from conda_forge_tick.env_management import global_sensitive_env


@pytest.fixture
def env_setup():
    old_pwd = os.environ.pop("PASSWORD", None)
    os.environ["PASSWORD"] = "unpassword"
    global_sensitive_env.classify()
    yield
    global_sensitive_env.declassify()
    if old_pwd:
        os.environ["PASSWORD"] = old_pwd
