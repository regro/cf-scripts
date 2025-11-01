import email.utils
from datetime import datetime
from typing import Annotated, Any, Generic, Literal, Never, TypeVar

from conda.exceptions import InvalidVersionSpec
from conda.models.version import VersionOrder
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    UrlConstraints,
)
from pydantic_core import Url

T = TypeVar("T")

K = TypeVar("K")
V = TypeVar("V")


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")


class ValidatedBaseModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="ignore")


def before_validator_ensure_dict(value: Any) -> dict:
    """Ensure that a value is a dictionary.

    Raises
    ------
    ValueError
        If the value is not a dictionary.
    """
    if not isinstance(value, dict):
        raise ValueError(
            "We only support validating dicts. Pydantic supports calling model_validate with some "
            "other objects (e.g. in conjunction with construct), but we do not. "
            "See https://docs.pydantic.dev/latest/concepts/validators/#model-validators"
        )
    return value


class Set(StrictBaseModel, Generic[T]):
    """
    A custom set type. It contains a special set marker `__set__`, allowing dynamic instantiation of the set type.
    This is considered legacy and should be removed if a proper data model is used for validation.
    """

    magic_set_marker: Literal[True] = Field(..., alias="__set__")
    elements: set[T]


def none_to_empty_list(value: T | None) -> T | list[Never]:
    """Convert `None` to an empty list. Everything else is kept as is."""
    if value is None:
        return []
    return value


NoneIsEmptyList = Annotated[list[T], BeforeValidator(none_to_empty_list)]
"""
A generic list type that converts `None` to an empty list.
This should not be needed if this proper data model is used in production.
Defining this type is already the first step to remove it.
"""


def none_to_empty_dict(value: T | None) -> T | dict[Never, Never]:
    """Convert `None` to an empty dict. Everything else is kept as is."""
    if value is None:
        return {}
    return value


NoneIsEmptyDict = Annotated[dict[K, V], BeforeValidator(none_to_empty_dict)]
"""
A generic dict type that converts `None` to an empty dict.
This should not be needed if this proper data model is used in production.
Defining this type is already the first step to remove it.
"""


def convert_to_list(value: T) -> list[T]:
    """Convert a single value to a list."""
    return [value]


SingleElementToList = Annotated[list[T], BeforeValidator(convert_to_list)]
"""
A generic list type that converts a single value to a list. Union with list[T] to allow multiple values.
"""


def empty_string_to_none(value: Any) -> None:
    """Convert an empty string to `None`. None is kept as is.

    Raises
    ------
    ValueError
        If the value is neither an empty string nor `None`.
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
    """Split a string by newlines.

    Raises
    ------
    ValueError
        If the value is not a string.
    """
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    return value.split("\n")


SplitStringNewlineBefore = Annotated[list[str], BeforeValidator(split_string_newline)]
"""
A generic list type that splits a string at newlines before validation.
"""


def false_to_none(value: Any) -> None:
    """Convert `False` to `None`. Keep `None` as is.

    Raises
    ------
    ValueError
        If the value is not `False` or `None`.
    """
    if value is False or value is None:
        return None
    raise ValueError("value must be False or None")


FalseIsNone = Annotated[None, BeforeValidator(false_to_none)]
"""
A type that can only receive `False` or `None` and converts it to `None`.
"""


def parse_rfc_2822_date(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    return email.utils.parsedate_to_datetime(value)


def serialize_rfc_2822_date(value: datetime) -> str:
    return email.utils.format_datetime(value)


RFC2822Date = Annotated[
    datetime,
    BeforeValidator(parse_rfc_2822_date),
    PlainSerializer(serialize_rfc_2822_date),
]


GitUrl = Annotated[Url, UrlConstraints(allowed_schemes=["git"])]


def try_parse_conda_version(value: str) -> str:
    try:
        VersionOrder(value)
    except InvalidVersionSpec as e:
        raise ValueError(f"Value '{value}' is not a valid conda version string: {e}")
    return value


CondaVersionString = Annotated[str, AfterValidator(try_parse_conda_version)]
"""
A string that matches conda version numbers.
"""

# TODO: There should be an elegant pydantic way to resolve LazyJSON references, generically


class PrInfoLazyJsonReference(StrictBaseModel):
    """A lazy reference to a pr_info JSON object."""

    json_reference: str = Field(pattern=r"pr_info/.*\.json$", alias="__lazy_json__")


class VersionPrInfoLazyJsonReference(StrictBaseModel):
    """A lazy reference to a version_pr_info JSON object."""

    json_reference: str = Field(
        pattern=r"version_pr_info/.*\.json$", alias="__lazy_json__"
    )


class PrJsonLazyJsonReference(StrictBaseModel):
    """A lazy reference to a pr_json JSON object."""

    json_reference: str = Field(pattern=r"pr_json/.*\.json$", alias="__lazy_json__")
