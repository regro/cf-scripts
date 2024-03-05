from pydantic import BaseModel

from conda_forge_tick.models.common import StrictBaseModel

"""
Refer to https://docs.conda.io/projects/conda-build/en/stable/resources/define-metadata.html for
a documentation of the fields.
"""


class Package(StrictBaseModel):
    name: str
    version: str | None = None
    """
    The version field can be missing if the `meta.yaml` outputs specify their own versions or if post-build versioning
    is used.
    https://docs.conda.io/projects/conda-build/en/stable/resources/define-metadata.html#package-version
    """


class Output(BaseModel):
    name: str
    version: str | None = None


class MetaYaml(BaseModel):
    package: Package
    outputs: list[Output] | None = None
