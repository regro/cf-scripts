from pydantic import TypeAdapter

from conda_forge_tick.models.common import StrictBaseModel, ValidatedBaseModel


class VersionsValid(StrictBaseModel):
    new_version: str | None
    """
    The latest upstream version found by the update_upstream_versions component.
    This value is read by the version migrator to perform the actual version bump.

    False or None indicates a problem in finding the next version or that the version migrator
    should not perform a version bump (e.g., because the latest version should be skipped).
    """


class VersionsBad(ValidatedBaseModel):
    bad: str
    """
    An error message indicating why searching for a new version failed.
    """


Versions = TypeAdapter(VersionsValid | VersionsBad)
