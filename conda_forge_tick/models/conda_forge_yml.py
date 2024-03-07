from enum import StrEnum
from typing import Literal

from pydantic import Field

from conda_forge_tick.models.common import (
    FalseIsNone,
    NoneIsEmptyDict,
    NoneIsEmptyList,
    SingleElementToList,
    StrictBaseModel,
    ValidatedBaseModel,
)

"""
Refer to https://conda-forge.org/docs/maintainer/conda_forge_yml for a documentation of the fields.

TODO Note: There is currently an open PR that aims to add a Pydantic model for the `conda-forge.yml` file to
conda-smithy. This PR is not yet merged, so the important parts of the model are defined here.

https://github.com/conda-forge/conda-smithy/pull/1756

In the future, cf-scripts should depend on conda-smithy to obtain the `conda-forge.yml` model from there.
"""


class BotInspection(StrEnum):
    HINT = "hint"
    HINT_ALL = "hint-all"
    HINT_SOURCE = "hint-source"
    HINT_GRAYSKULL = "hint-grayskull"
    UPDATE_ALL = "update-all"
    UPDATE_SOURCE = "update-source"
    UPDATE_GRAYSKULL = "update-grayskull"


class VersionSource(StrEnum):
    PYPI = "pypi"
    CRAN = "cran"
    NPM = "npm"
    ROS_DISTRO = "rosdistro"
    RAW_URL = "rawurl"
    GITHUB = "github"
    INCREMENT_ALPHA_RAW_URL = "incrementalpharawurl"
    NVIDIA = "nvidia"


class BotVersionUpdates(StrictBaseModel):
    random_fraction_to_keep: float = Field(0.0, ge=0.0, le=1.0)
    sources: SingleElementToList[VersionSource] | None = None
    exclude: NoneIsEmptyList[str] | SingleElementToList[str] = []


class Bot(StrictBaseModel):
    automerge: bool | Literal["version", "migration"] = False
    check_solvable: bool = False
    inspection: BotInspection = BotInspection.HINT
    abi_migration_branches: NoneIsEmptyList[str] | SingleElementToList[str] = []
    version_updates: BotVersionUpdates | None = None
    run_deps_from_wheel: bool = False


class BuildPlatform(StrEnum):
    """
    Build platforms prefixed with LEGACY were mentioned in the documentation for the `provider` field in the
    `conda-forge.yml` file but are no longer supported. A lot of feedstocks (03/2024: ~3000) still use them.
    They should be migrated to a non-legacy build platform.
    """

    LINUX_64 = "linux_64"
    LINUX_AARCH64 = "linux_aarch64"
    LINUX_PPC64LE = "linux_ppc64le"
    OSX_64 = "osx_64"
    WIN_64 = "win_64"
    WIN_ARM64 = "win_arm64"

    LEGACY_LINUX = "linux"
    LEGACY_OSX = "osx"
    LEGACY_WIN = "win"
    LEGACY_OSX_ARM64 = "osx_arm64"


class CIService(StrEnum):
    AZURE = "azure"
    CIRCLE = "circle"
    TRAVIS = "travis"
    APPVEYOR = "appveyor"
    GITHUB_ACTIONS = "github_actions"
    NATIVE = "native"
    EMULATED = "emulated"
    DEFAULT = "default"

    LEGACY_OSX_64 = "osx_64"


class CondaForgeYml(ValidatedBaseModel):
    bot: Bot | None = None

    provider: NoneIsEmptyDict[
        BuildPlatform,
        CIService | FalseIsNone,
    ] = {}
