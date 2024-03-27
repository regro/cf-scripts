from typing import Annotated, Any, Generic, Literal, Never, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, UrlConstraints
from pydantic_core import Url

T = TypeVar("T")

K = TypeVar("K")
V = TypeVar("V")


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


class ValidatedBaseModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="allow")


class Set(StrictBaseModel, Generic[T]):
    """
    A custom set type. It contains a special set marker `__set__`, allowing dynamic instantiation of the set type.
    This is considered legacy and should be removed if a proper data model is used for validation.
    """

    magic_set_marker: Literal[True] = Field(..., alias="__set__")
    elements: set[T]


def none_to_empty_list(value: T | None) -> T | list[Never]:
    """
    Convert `None` to an empty list. Everything else is kept as is.
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


def convert_to_list(value: T) -> list[T]:
    """
    Convert a single value to a list.
    """
    return [value]


SingleElementToList = Annotated[list[T], BeforeValidator(convert_to_list)]
"""
A generic list type that converts a single value to a list. Union with list[T] to allow multiple values.
"""


def empty_string_to_none(value: Any) -> None:
    """
    Convert an empty string to `None`. None is kept as is.
    """
    if value is None or value == "":
        return None
    raise ValueError("value must be an empty string or None")


EmptyStringIsNone = Annotated[None, BeforeValidator(empty_string_to_none)]
"""
A type that can only receive an empty string and converts it to `None`.
Can also hold `None` as is.
This should not be needed if a proper data model is used in production.
"""


def split_string_newline(value: Any) -> list[str]:
    """
    Split a string by newlines.
    """
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    return value.split("\n")


SplitStringNewlineBefore = Annotated[list[str], BeforeValidator(split_string_newline)]
"""
A generic list type that splits a string at newlines before validation.
"""


def false_to_none(value: Any) -> None:
    """
    Convert `False` to `None`. Keep `None` as is.
    """
    if value is False or value is None:
        return None
    raise ValueError("value must be False or None")


FalseIsNone = Annotated[None, BeforeValidator(false_to_none)]
"""
A type that can only receive `False` or `None` and converts it to `None`.
"""


def none_to_empty_dict(value: T | None) -> T | dict[Never, Never]:
    """
    Convert `None` to an empty dictionary, otherwise keep the value as is.
    """
    if value is None:
        return {}
    return value


NoneIsEmptyDict = Annotated[dict[K, V], BeforeValidator(none_to_empty_dict)]
"""
A generic dict type that converts `None` to an empty dict.
"""


GitUrl = Annotated[Url, UrlConstraints(allowed_schemes=["git"])]


class LazyJsonReference(StrictBaseModel):
    """
    A lazy reference to a JSON object.
    """

    # TODO: There should be an elegant pydantic way to resolve LazyJSON references.

    json_reference: str = Field(pattern=r".*\.json$", alias="__lazy_json__")
    """
    The JSON file reference.
    """
