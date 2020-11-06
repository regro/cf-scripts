import os
from contextlib import contextmanager


class SensitiveEnv():
    SENSITIVE_KEYS = ["USERNAME", "PASSWORD", "GITHUB_TOKEN", "GH_TOKEN"]

    def __init__(self):
        self.clasified_info = {}
        self.classify()

    def classify(self):
        self.clasified_info.update({k: os.environ.pop(k, None) for k in self.SENSITIVE_KEYS})

    def declassify(self):
        self.clasified_info.update(
            {k: os.environ.pop(k, None) for k in list(self.clasified_info)},
        )

    @contextmanager
    def sensitive_env(self):
        """Add sensitive keys to environ if needed, when ctx is finished remove keys and update the sensitive env
        in case any were updated inside the ctx"""
        os.environ.update(**self.clasified_info)
        yield os.environ
        self.clasified_info.update(
            {k: os.environ.pop(k, None) for k in list(self.clasified_info)},
        )

global_sensitive_env = SensitiveEnv()
sensitive_env = global_sensitive_env.sensitive_env