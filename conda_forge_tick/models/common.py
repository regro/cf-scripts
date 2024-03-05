import re
from typing import Annotated, Any, Generic, Literal, Never, TypeVar

from pydantic import BaseModel, BeforeValidator, Field

T = TypeVar("T")


class StrictBaseModel(BaseModel):
    class Config:
        validate_assignment = True
        extra = "forbid"


class ValidatedBaseModel(BaseModel):
    class Config:
        validate_assignment = True
        extra = "allow"


class Set(StrictBaseModel, Generic[T]):
    """
    A custom set type. It contains a special set marker `__set__`, allowing dynamic instantiation of the set type.
    This is considered legacy and should be removed if a proper data model is used for validation.
    """

    magic_set_marker: Literal[True] = Field(..., alias="__set__")
    elements: set[T]


def none_to_empty_list(value: T) -> T | list[Never]:
    """
    Convert `None` to an empty list.
    """
    if value is None:
        return []
    return value


NoneIsEmptyList = Annotated[list[T], BeforeValidator(none_to_empty_list)]
"""
A generic list type that converts `None` to an empty list.
This should not be needed if this proper data model is used in production.
Defining this type is already the first step to remove it.
"""


def split_string_newline(value: Any) -> list[str]:
    """
    Split a string by newlines.
    """
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    return value.split("\n")


SplitStringNewlineBefore = Annotated[list[T], BeforeValidator(split_string_newline)]
"""
A generic list type that splits a string at newlines before validation.
"""


class LazyJsonReference(StrictBaseModel):
    """
    A lazy reference to a JSON object.
    """

    # TODO: There should be an elegant pydantic way to resolve LazyJSON references.

    json_reference: str = Field(pattern=r".*\.json$", alias="__lazy_json__")
    """
    The JSON file reference.
    """
