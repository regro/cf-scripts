from typing import Any, Literal

from pydantic import TypeAdapter

from conda_forge_tick.models.common import StrictBaseModel, ValidatedBaseModel


class PrInfoValid(StrictBaseModel):
    PRed: Any
    bad: Literal[False] = False
    pinning_version: str
    smithy_version: str


class PrInfoError(ValidatedBaseModel):
    bad: str
    """
    Indicates an error that occurred while???
    """
    # TODO


PrInfo = TypeAdapter(PrInfoValid | PrInfoError)
