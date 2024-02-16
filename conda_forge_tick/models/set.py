from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Set(BaseModel, Generic[T]):
    """
    A custom set type. It contains a special set marker `__set__`, allowing dynamic instantiation of the set type.
    This is considered legacy and should be removed if a proper data model is used for validation.
    """

    magic_set_marker: Literal[True] = Field(..., alias="__set__")
    elements: set[T]
