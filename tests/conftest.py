import os

import pytest


@pytest.fixture
def env_setup():
    old_pwd = os.environ.pop("PASSWORD", None)
    os.environ["PASSWORD"] = "unpassword"
    yield
    if old_pwd:
        os.environ["PASSWORD"] = old_pwd
