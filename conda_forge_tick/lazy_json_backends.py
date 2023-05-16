import os
import hashlib
import functools
from typing import Any, Union, Optional, IO, Set, Iterator
from collections.abc import MutableMapping, Callable

import rapidjson as json


CF_TICK_GRAPH_DATA_BACKEND = os.environ.get("CF_TICK_GRAPH_DATA_BACKEND", "file")


@functools.lru_cache(maxsize=1)
def get_graph_data_redis_backend(db_name):
    if CF_TICK_GRAPH_DATA_BACKEND == "redislite":
        import redislite

        return redislite.StrictRedis(db_name)
    else:
        raise RuntimeError(
            "Did not recognize graph data backend %s" % CF_TICK_GRAPH_DATA_BACKEND,
        )


def get_sharded_path(file_path, n_dirs=5):
    """computed a sharded location for the LazyJson file."""
    top_dir, file_name = os.path.split(file_path)

    if len(top_dir) == 0:
        return file_path
    else:
        hx = hashlib.sha1(file_name.encode("utf-8")).hexdigest()[0:n_dirs]
        pth_parts = [top_dir] + [hx[i] for i in range(n_dirs)] + [file_name]
        return os.path.join(*pth_parts)


class LazyJson(MutableMapping):
    """Lazy load a dict from a json file and save it when updated"""

    def __init__(self, file_name: str):
        self.file_name = file_name
        self.sharded_path = get_sharded_path(file_name)
        self._data: Optional[dict] = None
        self._data_hash_at_load = None
        self._in_context = False

        # If the file doesn't exist and backend is file create an empty file
        # this is for backwards compat with old versions
        if CF_TICK_GRAPH_DATA_BACKEND == "file" and not os.path.exists(
            self.sharded_path,
        ):
            if os.path.split(self.sharded_path)[0]:
                os.makedirs(os.path.split(self.sharded_path)[0], exist_ok=True)
            with open(self.sharded_path, "w") as f:
                dump({}, f)

    @property
    def data(self):
        self._load()
        return self._data

    def clear(self):
        assert self._in_context
        self._load()
        self._data.clear()

    def __len__(self) -> int:
        self._load()
        assert self._data is not None
        return len(self._data)

    def __iter__(self) -> Iterator[Any]:
        self._load()
        assert self._data is not None
        yield from self._data

    def __delitem__(self, v: Any) -> None:
        assert self._in_context
        self._load()
        assert self._data is not None
        del self._data[v]

    def _load(self) -> None:
        if self._data is None:
            if not os.path.exists(self.sharded_path):
                # the data is not cached locally
                # so we pull from correct source
                if CF_TICK_GRAPH_DATA_BACKEND == "file":
                    # the file doesn't exist so create an empty file
                    if os.path.split(self.sharded_path)[0]:
                        os.makedirs(os.path.split(self.sharded_path)[0], exist_ok=True)
                    data_str = dumps({})
                    with open(self.sharded_path, "w") as f:
                        f.write(data_str)
                    self._data = {}
                elif CF_TICK_GRAPH_DATA_BACKEND == "redislite":
                    fparts = self.file_name.split("/")
                    if len(fparts) == 2:
                        key = fparts[0]
                        node = fparts[1][: -len(".json")]
                    else:
                        key = "lazy_json"
                        node = self.file_name[: -len(".json")]

                    self._rdkey = key
                    self._rdnode = node
                    rd = get_graph_data_redis_backend("cf-graph.db")
                    data_str = dumps({})
                    if rd.hsetnx(key, node, data_str):
                        # if a new node was created then it is empty
                        self._data = {}
                    else:
                        # nothing created so we read
                        data_str = rd.hget(self._rdkey, self._rdnode)
                        self._data = loads(data_str)
                else:
                    raise RuntimeError(
                        "Did not recognize graph data backend %s"
                        % CF_TICK_GRAPH_DATA_BACKEND,
                    )

                # cache and set the hash for later
                if CF_TICK_GRAPH_DATA_BACKEND != "file":
                    if os.path.split(self.sharded_path)[0]:
                        os.makedirs(os.path.split(self.sharded_path)[0], exist_ok=True)
                    with open(self.sharded_path, "w") as fp:
                        fp.write(data_str)

                self._data_hash_at_load = hashlib.sha256(
                    data_str.encode("utf-8"),
                ).hexdigest()
            else:
                # we have the data cached so read it
                with open(self.sharded_path) as f:
                    data_str = f.read()
                self._data_hash_at_load = hashlib.sha256(
                    data_str.encode("utf-8"),
                ).hexdigest()
                self._data = loads(data_str)

    def _dump(self, purge=False) -> None:
        self._load()
        data_str = dumps(self._data)
        curr_hash = hashlib.sha256(data_str.encode("utf-8")).hexdigest()
        if curr_hash != self._data_hash_at_load:
            with open(self.sharded_path, "w") as f:
                f.write(data_str)
            self._data_hash_at_load = curr_hash

            if CF_TICK_GRAPH_DATA_BACKEND == "file":
                pass
            elif CF_TICK_GRAPH_DATA_BACKEND == "redislite":
                rd = get_graph_data_redis_backend("cf-graph.db")
                rd.hset(self._rdkey, self._rdnode, data_str)
            else:
                raise RuntimeError(
                    "Did not recognize graph data backend %s"
                    % CF_TICK_GRAPH_DATA_BACKEND,
                )

        if purge:
            # this evicts the josn from memory and trades i/o for mem
            # the bot uses too much mem if we don't do this
            self._data = None
            self._data_hash_at_load = None

    def __getitem__(self, item: Any) -> Any:
        self._load()
        assert self._data is not None
        return self._data[item]

    def __setitem__(self, key: Any, value: Any) -> None:
        assert self._in_context
        self._load()
        assert self._data is not None
        self._data[key] = value

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["_data"] = None
        state["_data_hash_at_load"] = None
        return state

    def __enter__(self) -> "LazyJson":
        self._in_context = True
        return self

    def __exit__(self, *args: Any) -> Any:
        self._dump(purge=True)
        self._in_context = False


def default(obj: Any) -> Any:
    """For custom object serialization."""
    if isinstance(obj, LazyJson):
        return {"__lazy_json__": obj.file_name}
    elif isinstance(obj, Set):
        return {"__set__": True, "elements": sorted(obj)}
    raise TypeError(repr(obj) + " is not JSON serializable")


def object_hook(dct: dict) -> Union[LazyJson, Set, dict]:
    """For custom object deserialization."""
    if "__lazy_json__" in dct:
        return LazyJson(dct["__lazy_json__"])
    elif "__set__" in dct:
        return set(dct["elements"])
    return dct


def dumps(
    obj: Any,
    sort_keys: bool = True,
    separators: Any = (",", ":"),
    default: "Callable[[Any], Any]" = default,
    **kwargs: Any,
) -> str:
    """Returns a JSON string from a Python object."""
    return json.dumps(
        obj,
        sort_keys=sort_keys,
        # separators=separators,
        default=default,
        indent=1,
        **kwargs,
    )


def dump(
    obj: Any,
    fp: IO[str],
    sort_keys: bool = True,
    separators: Any = (",", ":"),
    default: "Callable[[Any], Any]" = default,
    **kwargs: Any,
) -> None:
    """Returns a JSON string from a Python object."""
    return json.dump(
        obj,
        fp,
        sort_keys=sort_keys,
        # separators=separators,
        default=default,
        indent=1,
        **kwargs,
    )


def loads(
    s: str, object_hook: "Callable[[dict], Any]" = object_hook, **kwargs: Any
) -> dict:
    """Loads a string as JSON, with appropriate object hooks"""
    return json.loads(s, object_hook=object_hook, **kwargs)


def load(
    fp: IO[str],
    object_hook: "Callable[[dict], Any]" = object_hook,
    **kwargs: Any,
) -> dict:
    """Loads a file object as JSON, with appropriate object hooks."""
    return json.load(fp, object_hook=object_hook, **kwargs)
