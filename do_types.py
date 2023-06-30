from __future__ import annotations

from typing import TYPE_CHECKING, Any, Union
from collections.abc import Callable, MutableMapping

if TYPE_CHECKING:
    # TODO import from typing (requires Python >=3.10)
    from typing_extensions import TypeAlias

WorkerDataParameter: TypeAlias = Union[
    # pre-initialized
    MutableMapping[str, object],
    # constructor
    Callable[[], MutableMapping[str, object]],
    # constructor, passed worker.local_directory
    Callable[[str], MutableMapping[str, object]],
    # (constructor, kwargs to constructor)
    tuple[Callable[..., MutableMapping[str, object]], dict[str, Any]],
    # initialize internally
    None,
]
