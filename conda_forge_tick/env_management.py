import os
from contextlib import contextmanager

# SENSITIVE_ENVIRON = {k: os.environ.pop(k, None) for k in ["USERNAME", "PASSWORD", "GITHUB_TOKEN"]}
SENSITIVE_ENVIRON = {k: os.environ.get(k, None) for k in ["USERNAME", "PASSWORD", "GITHUB_TOKEN"]}


@contextmanager
def sensitive_env():
    """Add sensitive keys to environ if needed, when ctx is finished remove keys and update the sensitive env
    in case any were updated inside the ctx"""
    # os.environ.update(**SENSITIVE_ENVIRON)
    yield os.environ
    SENSITIVE_ENVIRON.update({k: os.environ.pop(k, None) for k in list(SENSITIVE_ENVIRON)})
