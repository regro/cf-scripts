from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel


class BuildPlatform(str, Enum):
    def __str__(self):
        return self.value

    """
    Build platforms prefixed with LEGACY were mentioned in the documentation for the `provider` field in the
    `conda-forge.yml` file but are no longer supported. A lot of feedstocks (today: ~3000) still use them.
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


class CondaForgeYml(BaseModel):
    """
    Refer to https://conda-forge.org/docs/maintainer/conda_forge_yml for a documentation of the fields.
    """

    provider: Optional[
        dict[
            BuildPlatform,
            str | Literal[False] | None,
        ]
    ] = None

    # TODO: complete
