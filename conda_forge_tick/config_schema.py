import json
from enum import StrEnum
from inspect import cleandoc
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field

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


class BotConfigVersionUpdatesNVIDIA(BaseModel):
    """
    Dictates the behavior of the conda-forge auto-tick bot for version
    updates using the NVIDIA source.
    """

    compute_subdir: Optional[str] = Field(
        default=None,
        description="For sources from `developer.download.nvidia.com/compute`, this string"
        "defines the subdirectory in which to find the JSON blob containing metadata"
        "about the latest releases of a package.",
    )

    json_name: Optional[str] = Field(
        default=None,
        description="For sources from `developer.download.nvidia.com/compute`, this string"
        "defines the name of the package in the JSON blob containing metadata"
        "about the latest releases of a package.",
    )


class BotConfigVersionUpdates(BaseModel):
    """
    Dictates the behavior of the conda-forge auto-tick bot for version
    updates.
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
            - `gittags`: Update from the listing of tags for sources that use git URLS.
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

    even_odd_versions: Optional[bool] = Field(
        default=None,
        description="For projects that follow even/odd versioning schemes (like GNOME), "
        "set to true to only accept stable versions (even minor numbers: 1.2.x, 1.4.x) "
        "and ignore development versions (odd minor numbers: 1.1.x, 1.3.x). "
        "Leave unset for projects that don't follow this versioning scheme.",
    )

    allowed_tag_globs: Optional[Union[str, list[str]]] = Field(
        default=None,
        description="For version sources that parse repo/vcs tags (e.g., "
        "`gittags`, `github`, `githubreleases`), "
        "the list of glob patterns that define which tags are allowed. This field can be used to "
        "filter the set of tags to only those relevant for the feedstock.",
    )

    nvidia: Optional[BotConfigVersionUpdatesNVIDIA] = Field(
        default_factory=BotConfigVersionUpdatesNVIDIA,
        description="Bot config for version update PRs using the NVIDIA updater.",
    )

    use_curl: Optional[bool] = Field(
        None,
        description="If True, use `curl` to test if URLs exist, otherwise use `wget`.",
    )


class BotConfig(BaseModel):
    """
    Dictates the behavior of the conda-forge auto-tick bot which issues
    automatic version updates/migrations for feedstocks.

    A valid example is:

    ```yaml
    bot:
        # can the bot automerge PRs it makes on this feedstock
        automerge: true
        # only automerge on successful version PRs, migrations are not automerged
        automerge: 'version'
        # only automerge on successful migration PRs, versions are not automerged
        automerge: 'migration'

        # only open PRs if resulting environment is solvable, useful for tightly coupled packages
        check_solvable: true

        # The bot.inspection key in the conda-forge.yml can have one of seven possible values and controls
        # the bots behaviour for automatic dependency updates:
        inspection: hint  # generate hints using source code (backwards compatible)
        inspection: hint-all  # generate hints using all methods
        inspection: hint-source  # generate hints using only source code
        inspection: hint-grayskull  # generate hints using only grayskull
        inspection: update-all  # update recipe using all methods
        inspection: update-source  # update recipe using only source code
        inspection: update-grayskull  # update recipe using only grayskull
        inspection: disabled # don't update recipe, don't generate hints

        # any branches listed in this section will get bot migration PRs in addition
        # to the default branch
        abi_migration_branches:
            - 'v1.10.x'

        version_updates:
            # use this for packages that are updated too frequently
            random_fraction_to_keep: 0.1  # keeps 10% of versions at random
            exclude:
                - '08.14'
            # even/odd version filtering for unstable versions
            even_odd_versions: true
            allowed_tag_globs: 'python-*'
            sources:
                - rawurl
            use_curl: true
    ```

    The `abi_migration_branches` feature is useful to, for example, add a
    long-term support (LTS) branch for a package.
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

    remake_prs_with_conflicts: Optional[bool] = Field(
        default=True,
        description="Automatically remake untouched bot PRs with conflicts.",
    )


if __name__ == "__main__":
    # This is used to generate the model dump for conda-smithy internal use
    # and for documentation purposes.

    model = BotConfig()

    with CF_TICK_SCHEMA_FILE.open(mode="w+", encoding="utf-8") as f:
        obj = model.model_json_schema()
        f.write(json.dumps(obj, indent=2))
        f.write("\n")
