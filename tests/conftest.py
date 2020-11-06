import os

import pytest


@pytest.fixture
def env_setup():
    old_pwd = os.environ.pop("PASSWORD", None)
    os.environ["PASSWORD"] = "unpassword"
    old_pwd2 = os.environ.pop("pwd", None)
    os.environ["pwd"] = "pwd"
    yield
    if old_pwd:
        os.environ["PASSWORD"] = old_pwd
    if old_pwd2:
        os.environ["pwd"] = old_pwd2
