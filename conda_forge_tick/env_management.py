import os
from contextlib import contextmanager


class SensitiveEnv:
    SENSITIVE_KEYS = [
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "BOT_TOKEN",
        "MONGODB_CONNECTION_STRING",
    ]

    def __init__(self):
        self.classified_info = {}

    def hide_env_vars(self):
        """Remove sensitive env vars."""
        self.classified_info.update(
            {
                k: os.environ.pop(k, self.classified_info.get(k, None))
                for k in self.SENSITIVE_KEYS
            },
        )

    def reveal_env_vars(self):
        """Restore sensitive env vars."""
        os.environ.update(
            **{k: v for k, v in self.classified_info.items() if v is not None}
        )

    @contextmanager
    def sensitive_env(self):
        """Add sensitive keys to environ if needed, when ctx is finished remove keys and update the sensitive env
        in case any were updated inside the ctx.
        """
        self.reveal_env_vars()
        yield os.environ
        self.hide_env_vars()
