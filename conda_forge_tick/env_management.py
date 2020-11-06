import os
from contextlib import contextmanager


class SensitiveEnv:
    SENSITIVE_KEYS = ["USERNAME", "PASSWORD", "GITHUB_TOKEN", "GH_TOKEN"]

    def __init__(self):
        self.clasified_info = {}

    def hide_env_vars(self):
        """Remove sensitive env vars"""
        self.clasified_info.update(
            {
                k: os.environ.pop(k, self.clasified_info.get(k, None))
                for k in self.SENSITIVE_KEYS
            },
        )

    def reveal_env_vars(self):
        """Restore sensitive env vars"""
        os.environ.update(
            **{k: v for k, v in self.clasified_info.items() if v is not None}
        )

    @contextmanager
    def sensitive_env(self):
        """Add sensitive keys to environ if needed, when ctx is finished remove keys and update the sensitive env
        in case any were updated inside the ctx"""
        self.reveal_env_vars()
        yield os.environ
        self.hide_env_vars()
