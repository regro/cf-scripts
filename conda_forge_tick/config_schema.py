import json
from inspect import cleandoc
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field

try:
    from enum import StrEnum
except ImportError:
    from backports.strenum import StrEnum


CF_TICK_SCHEMA_FILE = Path(__file__).resolve().parent / "cf_tick_schema.json"


class BotConfigAutoMergeChoice(StrEnum):
    VERSION = "version"
    MIGRATION = "migration"


class BotConfigInspectionChoice(StrEnum):
    HINT = "hint"
    HINT_ALL = "hint-all"
    HINT_SOURCE = "hint-source"
    HINT_GRAYSKULL = "hint-grayskull"
    UPDATE_ALL = "update-all"
    UPDATE_SOURCE = "update-source"
    UPDATE_GRAYSKULL = "update-grayskull"
    DISABLED = "disabled"


class BotConfigVersionUpdatesSourcesChoice(StrEnum):
    # if adding a new source here, make sure to update the description of the sources field
    # in the BotConfigVersionUpdates model as well
    CRAN = "cran"
    GITHUB = "github"
    GITHUB_RELEASES = "githubreleases"
    INCREMENT_ALPHA_RAW_URL = "incrementalpharawurl"
    LIBRARIES_IO = "librariesio"
    NPM = "npm"
    NVIDIA = "nvidia"
    PYPI = "pypi"
    RAW_URL = "rawurl"
    ROS_DISTRO = "rosdistro"


class BotConfigVersionUpdates(BaseModel):
    """
    This dictates the behavior of the conda-forge auto-tick bot for version
    updates
    """

    model_config: ConfigDict = ConfigDict(extra="forbid")

    random_fraction_to_keep: Optional[float] = Field(
        None,
        description="Fraction of versions to keep for frequently updated packages",
    )

    exclude: Optional[list[str]] = Field(
        default=[],
        description="List of versions to exclude. "
        "Make sure branch names are `str` by quoting the value.",
    )

    sources: Optional[list[BotConfigVersionUpdatesSourcesChoice]] = Field(
        None,
        description=cleandoc(
            """
            List of sources to find new versions (i.e. the strings like 1.2.3) for the package.
            The following sources are available:
            - `cran`: Update from CRAN
            - `github`: Update from the GitHub releases RSS feed (includes pre-releases)
            - `githubreleases`: Get the latest version by following the redirect of
            `https://github.com/{owner}/{repo}/releases/latest` (excludes pre-releases)
            - `incrementalpharawurl`: If this source is run for a specific small selection of feedstocks, it acts like
            the `rawurl` source but also increments letters in the version string (e.g. 2024a -> 2024b). If the source
            is run for other feedstocks (even if selected manually), it does nothing.
            - `librariesio`: Update from Libraries.io RSS feed
            - `npm`: Update from the npm registry
            - `nvidia`: Update from the NVIDIA download page
            - `pypi`: Update from the PyPI registry
            - `rawurl`: Update from a raw URL by trying to bump the version number in different ways and
            checking if the URL exists (e.g. 1.2.3 -> 1.2.4, 1.3.0, 2.0.0, etc.)
            - `rosdistro`: Update from a ROS distribution
            Common issues:
            - If you are using a GitHub-based source in your recipe and the bot issues PRs for pre-releases, restrict
            the sources to `githubreleases` to avoid pre-releases.
            - If you use source tarballs that are uploaded manually by the maintainers a significant time after a
            GitHub release, you may want to restrict the sources to `rawurl` to avoid the bot attempting to update
            the recipe before the tarball is uploaded.
            """
        ),
    )

    skip: Optional[bool] = Field(
        default=False,
        description="Skip automatic version updates. "
        "Useful in cases where the source project's version numbers don't conform to "
        "PEP440.",
    )


class BotConfig(BaseModel):
    """
    This dictates the behavior of the conda-forge auto-tick bot which issues
    automatic version updates/migrations for feedstocks.
    """

    model_config: ConfigDict = ConfigDict(extra="forbid")

    automerge: Optional[Union[bool, BotConfigAutoMergeChoice]] = Field(
        False,
        description="Automatically merge PRs if possible",
    )

    check_solvable: Optional[bool] = Field(
        default=True,
        description="Open PRs only if resulting environment is solvable.",
    )

    inspection: Optional[BotConfigInspectionChoice] = Field(
        default="hint",
        description="Method for generating hints or updating recipe",
    )

    abi_migration_branches: Optional[list[str]] = Field(
        default=[],
        description="List of branches for additional bot migration PRs. "
        "Make sure branch names are `str` by quoting the value.",
    )

    run_deps_from_wheel: Optional[bool] = Field(
        default=False,
        description="Update run dependencies from the pip wheel",
    )

    version_updates: Optional[BotConfigVersionUpdates] = Field(
        default_factory=BotConfigVersionUpdates,
        description="Bot config for version update PRs",
    )

    update_static_libs: Optional[bool] = Field(
        default=False,
        description="Update packages in `host` that are used for static "
        "linking. For bot to issue update PRs, you must have both an "
        "abstract specification of the library (e.g., `llvmdev 15.0.*`) "
        "and a concrete specification (e.g., `llvmdev 15.0.7 *_5`). The "
        "bot will find the latest package that satisfies the abstract "
        "specification and update the concrete specification to this "
        "latest package.",
    )


if __name__ == "__main__":
    # This is used to generate the model dump for conda-smithy internal use
    # and for documentation purposes.

    model = BotConfig()

    with CF_TICK_SCHEMA_FILE.open(mode="w+", encoding="utf-8") as f:
        obj = model.model_json_schema()
        f.write(json.dumps(obj, indent=2))
        f.write("\n")
