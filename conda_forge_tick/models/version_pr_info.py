from typing import Literal, Optional

from pydantic import TypeAdapter, model_validator

from conda_forge_tick.models.common import StrictBaseModel


class VersionPrInfo(StrictBaseModel):
    bad: str | Literal[False] = False
    """
    If this value is non-False, the string indicates the error.
    """

    new_version: str | Literal[False] = False
    """
    The latest version found by update_upstream_versions, which is copied from `versions` in the beginning of the
    auto_tick run.
    """

    new_version_attempts: Optional[dict[str, int | float]] = None
    """
    Mapping (version -> number of attempts) to describe the number of attempts that were made to update the versions in
    the PR. The value can be a float since failing with a solving error is counted as a partial attempt, which only
    increases the count by a fraction that is specified in auto_tick.run (03/2024: 0.2).
    """

    new_version_errors: Optional[dict[str, str]] = None
    """
    Mapping (version -> error message) to describe the errors that occurred when trying to update the versions in the
    PR.
    """

    @model_validator(mode="after")
    def check_new_version_error_keys(self):
        nve = getattr(self, "new_version_errors", {}) or {}
        nva = getattr(self, "new_version_attempts", {}) or {}
        wrong_versions = [version for version in nve if version not in nva]

        if wrong_versions:
            raise ValueError(
                f"new_version_errors contains at least one version not in new_version_attempts: {wrong_versions}"
            )


VersionPrInfo = TypeAdapter(VersionPrInfo)
