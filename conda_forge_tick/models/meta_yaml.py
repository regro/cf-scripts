from pydantic import BaseModel

from conda_forge_tick.models.common import StrictBaseModel

"""
Refer to https://docs.conda.io/projects/conda-build/en/stable/resources/define-metadata.html for
a documentation of the fields.
"""


class Package(StrictBaseModel):
    name: str
    version: str


class MetaYaml(BaseModel):
    package: Package
