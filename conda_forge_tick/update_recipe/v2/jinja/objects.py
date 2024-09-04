from __future__ import annotations


class _StubEnv:
    """A class to represent the env object used in rattler-build recipe."""

    def get(self, env_var: str, default: str | None = None) -> str:  # noqa: ARG002
        return f"""env_"{env_var}" """

    def exists(self, env_var: str) -> str:
        return f"""env_exists_"{env_var}" """


def _stub_compatible_pin(*args, **kwargs) -> str:  # noqa: ARG001, ANN003, ANN002
    return f"compatible_pin {args[0]}"


def _stub_subpackage_pin(*args, **kwargs) -> str:  # noqa: ARG001, ANN003, ANN002
    return f"subpackage_pin {args[0]}"


def _stub_match(*args, **kwargs) -> str:  # noqa: ARG001, ANN003, ANN002
    return f"match {args[0]}"


def _stub_is_unix(platform: str) -> str:
    return f"is_unix {platform}"


def _stub_is_win(platform: str) -> str:
    return f"is_win {platform}"


def _stub_is_linux(platform: str) -> str:
    return f"is_linux {platform}"
