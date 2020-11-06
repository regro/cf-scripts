import os

import pytest


@pytest.fixture
def env_setup():
    old_pwd = os.environ.pop('PASSWORD', None)
    os.environ['PASSWORD'] = 'not a password'
    yield
    if old_pwd:
        os.environ['PASSWORD'] = old_pwd
