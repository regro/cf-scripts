from xonsh.main import setup

setup()
del setup

from .env_management import SensitiveEnv

global_sensitive_env = SensitiveEnv()
global_sensitive_env.hide_env_vars()
sensitive_env = global_sensitive_env.sensitive_env