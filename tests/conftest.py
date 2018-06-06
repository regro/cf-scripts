import os

import pytest


@pytest.fixture
def tmpdir():
    if not os.path.exists('tmp'):
        os.makedirs('tmp')
    return 'tmp'
