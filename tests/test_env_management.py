import os

from conda_forge_tick.env_management import SensitiveEnv


def test_simple_sensitive_env(env_setup):
    os.environ["PASSWORD"] = "hi"
    s = SensitiveEnv()

    s.hide_env_vars()
    assert "PASSWORD" not in os.environ

    s.reveal_env_vars()
    assert "PASSWORD" in os.environ
    assert os.environ["PASSWORD"] == "hi"


def test_ctx_sensitive_env(env_setup):
    os.environ["PASSWORD"] = "hi"
    s = SensitiveEnv()

    with s.sensitive_env():
        assert "PASSWORD" in os.environ
        assert os.environ["PASSWORD"] == "hi"
    assert "PASSWORD" not in os.environ


def test_double_sensitive_env(env_setup):
    os.environ["PASSWORD"] = "hi"
    os.environ["pwd"] = "hello"
    s = SensitiveEnv()
    s.hide_env_vars()
    s.SENSITIVE_KEYS.append("pwd")
    s.hide_env_vars()
    s.reveal_env_vars()
    assert os.environ["pwd"] == "hello"
    assert os.environ["PASSWORD"] == "hi"
