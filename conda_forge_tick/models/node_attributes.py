from pydantic import BaseModel, Field

from conda_forge_tick.models.conda_forge_yml import CondaForgeYml


class NodeAttributes(BaseModel):
    archived: bool
    """
    Is the feedstock repository archived?
    Archived feedstocks are excluded from most bot operations and never receive updates.
    """

    branch: str
    """
    The branch of the feedstock repository to track. This is usually the default branch of the feedstock repository.
    For new feedstocks, this defaults to `main`.
    """

    conda_forge_yml: CondaForgeYml = Field(alias="conda-forge.yml")
    """
    A parsed representation of the `conda-forge.yml` file in the feedstock repository.
    """

    raw_meta_yaml: str
    """
    The raw content of the `recipe/meta.yaml` file in the feedstock repository.
    """

    # TODO: continue
