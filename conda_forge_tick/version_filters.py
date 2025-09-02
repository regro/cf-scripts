"""Version filtering utilities for conda-forge bot.

This module provides centralized logic for filtering versions based on
various criteria configured in conda-forge.yml files.
"""

import logging
from typing import Any, Mapping, Union

from conda_forge_tick.utils import get_keys_default

logger = logging.getLogger(__name__)


def is_version_ignored(attrs: Mapping[str, Any], version: str) -> bool:
    """Check if a version should be ignored based on the `conda-forge.yml` file.

    It handles both explicit version exclusions and odd/even version filtering.

    Parameters
    ----------
    attrs
        The node attributes containing conda-forge.yml configuration.
    version
        The version string to check.

    Returns
    -------
    bool
        True if the version should be ignored, False otherwise.
    """
    version_updates = get_keys_default(
        attrs,
        ["conda-forge.yml", "bot", "version_updates"],
        {},
        {},
    )

    normalized_version = version.replace("-", ".").replace("_", ".")

    versions_to_ignore = version_updates.get("exclude", [])
    if normalized_version in versions_to_ignore or version in versions_to_ignore:
        logger.debug("Version %s is explicitly excluded in conda-forge.yml", version)
        return True

    if version_updates.get("even_odd_versions", False):
        try:
            version_parts = normalized_version.split(".")
            if len(version_parts) >= 2 and int(version_parts[1]) % 2 == 1:
                logger.debug(
                    "Version %s has odd minor version (%s) and even_odd_versions is enabled",
                    version,
                    version_parts[1],
                )
                return True
        except (ValueError, IndexError):
            logger.debug("Could not parse version %s for odd/even filtering", version)
            pass

    return False


def filter_version(attrs: Mapping[str, Any], version) -> Union[str, bool]:
    """Filter a version, returning False if ignored, version otherwise.

    Parameters
    ----------
    attrs
        The node attributes containing conda-forge.yml configuration.
    version
        The version to check (can be string, False, or other types).

    Returns
    -------
    Union[str, bool]
        False if the version should be ignored, the original version otherwise.
    """
    if version and is_version_ignored(attrs, str(version)):
        return False
    else:
        return version
