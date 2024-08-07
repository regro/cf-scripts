from __future__ import annotations

from rattler_build_conda_compat.jinja.utils import _MissingUndefined


def _version_to_build_string(some_string: str | _MissingUndefined) -> str:
    """
    Converts some version by removing the . character and returning only the first two elements of the version.
    If piped value is undefined, it returns the undefined value as is.
    """
    if isinstance(some_string, _MissingUndefined):
        return f"{some_string._undefined_name}_version_to_build_string"  # noqa: SLF001
    # We first split the string by whitespace and take the first part
    split = some_string.split()[0] if some_string.split() else some_string
    # We then split the string by . and take the first two parts
    parts = split.split(".")
    major = parts[0] if len(parts) > 0 else ""
    minor = parts[1] if len(parts) > 1 else ""
    return f"{major}{minor}"


def _bool(value: str) -> bool:
    return bool(value)


def _split(s: str, sep: str = " ") -> list[str]:
    """Filter that split a string by a separator"""
    return s.split(sep)
