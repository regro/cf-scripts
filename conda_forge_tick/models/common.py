from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field, constr

T = TypeVar("T")


class StrictBaseModel(BaseModel):
    class Config:
        validate_assignment = True
        extra = "forbid"


class Set(StrictBaseModel, Generic[T]):
    """
    A custom set type. It contains a special set marker `__set__`, allowing dynamic instantiation of the set type.
    This is considered legacy and should be removed if a proper data model is used for validation.
    """

    magic_set_marker: Literal[True] = Field(..., alias="__set__")
    elements: set[T]


class LazyJsonReference(StrictBaseModel):
    """
    A lazy reference to a JSON object.
    """

    # TODO: There should be an elegant pydantic way to resolve LazyJSON references.

    json_reference: str = Field(pattern=r".*\.json$", alias="__lazy_json__")
    """
    The JSON file reference.
    """
