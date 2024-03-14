from typing import Literal

from pydantic import TypeAdapter, model_validator

from conda_forge_tick.models.common import StrictBaseModel, ValidatedBaseModel


class VersionPrInfoValid(ValidatedBaseModel):
    bad: Literal[False] = False
    """
    If this value is non-False, the file data is not necessarily valid and should be parsed as VersionPrInfoError.
    """

    new_version: str | Literal[False] = False
    """
    The latest version found by update_upstream_versions, which is copied from `versions` in the beginning of the
    auto_tick run.
    """

    new_version_attempts: dict[str, int | float]
    """
    Mapping (version -> number of attempts) to describe the number of attempts that were made to update the versions in
    the PR. The value can be a float since failing with a solving error is counted as a partial attempt, which only
    increases the count by a fraction that is specified in auto_tick.run (03/2024: 0.2).
    """

    new_version_errors: dict[str, str]
    """
    Mapping (version -> error message) to describe the errors that occurred when trying to update the versions in the
    PR.
    """

    @model_validator(mode="after")
    def check_new_version_error_keys(self):
        wrong_versions = [
            version
            for version in self.new_version_errors
            if version not in self.new_version_attempts
        ]

        if wrong_versions:
            raise ValueError(
                f"new_version_errors contains at least one version not in new_version_attempts: {wrong_versions}"
            )


class VersionPrInfoError(StrictBaseModel):
    bad: str


VersionPrInfo = TypeAdapter(VersionPrInfoValid | VersionPrInfoError)
