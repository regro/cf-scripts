from __future__ import annotations

import copy
import logging
import re
from typing import TYPE_CHECKING, Literal

from conda_forge_tick.update_recipe.v2.context import load_recipe_context
from conda_forge_tick.update_recipe.v2.jinja import jinja_env
from conda_forge_tick.update_recipe.v2.source import Source, get_all_sources
from conda_forge_tick.update_recipe.v2.yaml import _dump_yaml_to_str, _load_yaml
from conda_forge_tick.update_recipe.version import _try_url_and_hash_it

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

HashType = Literal["md5", "sha256"]


class CouldNotUpdateVersionError(Exception):
    NO_CONTEXT = "Could not find context in recipe"
    NO_VERSION = "Could not find version in recipe context"

    def __init__(self, message: str = "Could not update version") -> None:
        self.message = message
        super().__init__(self.message)


class HashError(Exception):
    def __init__(self, url: str) -> None:
        self.url = url
        self.message = f"Could not hash {url}"
        super().__init__(self.message)


class Hash:
    def __init__(self, hash_type: HashType, hash_value: str) -> None:
        self.hash_type = hash_type
        self.hash_value = hash_value

    def __str__(self) -> str:
        return f"{self.hash_type}: {self.hash_value}"


def _has_jinja_version(url: str) -> bool:
    """Check if the URL has a jinja `${{ version }}` in it."""
    pattern = r"\${{\s*version"
    return re.search(pattern, url) is not None


def update_hash(source: Source, url: str, hash_: Hash | None) -> None:
    """
    Update the sha256 hash in the source dictionary.

    Arguments:
    ----------
    * `source` - The source dictionary to update.
    * `url` - The URL to download and hash (if no hash is provided).
    * `hash_` - The hash to use. If not provided, the file will be downloaded and `sha256` hashed.
    """
    hash_type: HashType = hash_.hash_type if hash_ is not None else "sha256"
    # delete all old hashes that we are not updating
    all_hash_types: set[HashType] = {"md5", "sha256"}
    for key in all_hash_types - {hash_type}:
        if key in source:
            del source[key]

    if hash_ is not None:
        source[hash_.hash_type] = hash_.hash_value
    else:
        # download and hash the file
        logger.debug(f"Retrieving and hashing {url}")
        new_hash = _try_url_and_hash_it(url, "sha256")
        if new_hash is None:
            logger.error(f"Could not hash {url}")
            raise HashError(url)
        source["sha256"] = new_hash


def update_version(
    file: Path, new_version: str, hash_: Hash | None
) -> (str | None, set[str]):
    """
    Update the version in the recipe file.

    Arguments:
    ----------
    * `file` - The path to the recipe file.
    * `new_version` - The new version to use.
    * `hash_type` - The hash type to use. If not provided, the file will be downloaded and `sha256` hashed.

    Returns:
    --------
    The updated recipe as a string.
    """

    data = _load_yaml(file)

    if "context" not in data:
        # raise CouldNotUpdateVersionError(CouldNotUpdateVersionError.NO_CONTEXT)
        return None, {CouldNotUpdateVersionError.NO_CONTEXT}
    if "version" not in data["context"]:
        return None, {CouldNotUpdateVersionError.NO_VERSION}

    data["context"]["version"] = new_version

    # set up the jinja context
    env = jinja_env()
    context = copy.deepcopy(data.get("context", {}))
    context_variables = load_recipe_context(context, env)
    # for r-recipes we add the default `cran_mirror` variable
    context_variables["cran_mirror"] = "https://cran.r-project.org"

    for source in get_all_sources(data):
        # render the whole URL and find the hash
        if "url" not in source:
            continue

        url = source["url"]
        if isinstance(url, list):
            url = url[0]

        if not _has_jinja_version(url):
            continue

        template = env.from_string(url)
        rendered_url = template.render(context_variables)
        try:
            update_hash(source, rendered_url, hash_)
        except HashError:
            return None, set(f"Could not retrieve hash for '{rendered_url}'")

    return _dump_yaml_to_str(data), {}
