import os
import hashlib
import glob
import subprocess
import tqdm
import joblib

from typing import Any, Union, Optional, IO, Set, Iterator
from collections.abc import MutableMapping, Callable

import rapidjson as json

from conda_forge_tick.os_utils import pushd

CF_TICK_GRAPH_DATA_BACKENDS = tuple(
    os.environ.get("CF_TICK_GRAPH_DATA_BACKENDS", "file").split(":"),
)
CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = CF_TICK_GRAPH_DATA_BACKENDS[0]

CF_TICK_GRAPH_DATA_HASHMAPS = [
    "pr_json",
    "pr_info",
    "version_pr_info",
    "versions",
    "node_attrs",
]


def get_sharded_path(file_path, n_dirs=5):
    """computed a sharded location for the LazyJson file."""
    top_dir, file_name = os.path.split(file_path)

    if len(top_dir) == 0 or top_dir == "lazy_json":
        return file_name
    else:
        hx = hashlib.sha1(file_name.encode("utf-8")).hexdigest()[0:n_dirs]
        pth_parts = [top_dir] + [hx[i] for i in range(n_dirs)] + [file_name]
        return os.path.join(*pth_parts)


class LazyJsonBackend:
    def unload_to_disk(self, name):
        raise NotImplementedError

    def hexists(self, name, key):
        raise NotImplementedError

    def hset(self, name, key, value):
        raise NotImplementedError

    def hdel(self, name, key):
        raise NotImplementedError

    def hkeys(self, name):
        raise NotImplementedError

    def hsetnx(self, name, key, value):
        if self.hexists(name, key):
            return False
        else:
            self.hset(name, key, value)
            return True

    def hget(self, name, key):
        raise NotImplementedError


class FileLazyJsonBackend(LazyJsonBackend):
    def unload_to_disk(self, name):
        pass

    def hexists(self, name, key):
        return os.path.exists(get_sharded_path(f"{name}/{key}.json"))

    def hset(self, name, key, value):
        sharded_path = get_sharded_path(f"{name}/{key}.json")
        if os.path.split(sharded_path)[0]:
            os.makedirs(os.path.split(sharded_path)[0], exist_ok=True)
        with open(sharded_path, "w") as f:
            f.write(value)

    def hdel(self, name, keys):
        for key in keys:
            lzj_name = get_sharded_path(f"{name}/{key}.json")
            subprocess.run(
                "git rm -f " + lzj_name,
                shell=True,
                check=True,
            )
            subprocess.run(
                "rm -f " + lzj_name,
                shell=True,
                check=True,
            )

    def hkeys(self, name):
        if name == "lazy_json":
            name = "."
        jlen = len(".json")
        fnames = glob.glob(os.path.join(name, "**/*.json"), recursive=True)
        return [os.path.basename(fname)[:-jlen] for fname in fnames]

    def hget(self, name, key):
        sharded_path = get_sharded_path(f"{name}/{key}.json")
        with open(sharded_path) as f:
            data_str = f.read()
        return data_str


LAZY_JSON_BACKENDS = {
    "file": FileLazyJsonBackend,
}


def sync_lazy_json_across_backends():
    """Sync data from the primary backend to the secondary ones.

    If there is only one backend, this is a no-op.

    **This operation is serial and very expensive!**
    """

    def _sync_node(hashmap):
        nodes = get_all_keys_for_hashmap(hashmap)
        for node in tqdm.tqdm(nodes, desc=f"syncing {hashmap}", ncols=80):
            LazyJson(f"{hashmap}/{node}.json").sync_across_backends()

    if len(CF_TICK_GRAPH_DATA_BACKENDS) > 1:
        jobs = [
            joblib.delayed(_sync_node)(hashmap)
            for hashmap in CF_TICK_GRAPH_DATA_HASHMAPS
        ]
        with joblib.Parallel(
            n_jobs=len(CF_TICK_GRAPH_DATA_HASHMAPS),
            backend="loky",
            verbose=100,
        ) as par:
            par(jobs)
        LazyJson("graph.json").sync_across_backends()


def cache_lazy_json_to_disk(dest_dir="."):
    with pushd(dest_dir):
        for hashmap in CF_TICK_GRAPH_DATA_HASHMAPS + ["lazy_json"]:
            cache_all_keys_for_hashmap(hashmap, force=True)


def cache_all_keys_for_hashmap(name, force=False):
    if "/" in name:
        name = hashlib.sha256(
            name.encode("utf-8"),
        ).hexdigest()

    ffname = ".unload_to_disk_" + name + "_" + CF_TICK_GRAPH_DATA_PRIMARY_BACKEND
    if (not os.path.exists(ffname)) or force:
        from conda_forge_tick.executors import PRLOCK, TRLOCK, DLOCK

        def _do_the_thing():
            if (not os.path.exists(ffname)) or force:
                LAZY_JSON_BACKENDS[CF_TICK_GRAPH_DATA_PRIMARY_BACKEND]().unload_to_disk(
                    name,
                )
                with open(ffname, "w") as fp:
                    fp.write("done")

        with TRLOCK:
            with PRLOCK:
                with DLOCK:
                    _do_the_thing()


def remove_key_for_hashmap(name, node):
    """Remove the key node for hashmap name."""
    for backend_name in CF_TICK_GRAPH_DATA_BACKENDS:
        backend = LAZY_JSON_BACKENDS[backend_name]()
        backend.hdel(name, [node])


def get_all_keys_for_hashmap(name):
    """Get all keys for the hashmap `name`."""
    backend = LAZY_JSON_BACKENDS[CF_TICK_GRAPH_DATA_PRIMARY_BACKEND]()
    return backend.hkeys(name)


class LazyJson(MutableMapping):
    """Lazy load a dict from a json file and save it when updated"""

    def __init__(self, file_name: str):
        self.file_name = file_name
        self._data: Optional[dict] = None
        self._data_hash_at_load = None
        self._in_context = False
        fparts = os.path.split(self.file_name)
        if len(fparts[0]) > 0:
            key = fparts[0]
            node = fparts[1][: -len(".json")]
        else:
            key = "lazy_json"
            node = self.file_name[: -len(".json")]
        self.hashmap = key
        self.node = node

        # make this backwards compatible with old behavior
        if CF_TICK_GRAPH_DATA_PRIMARY_BACKEND == "file":
            LAZY_JSON_BACKENDS[CF_TICK_GRAPH_DATA_PRIMARY_BACKEND]().hsetnx(
                self.hashmap,
                self.node,
                dumps({}),
            )

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
            # cache the data for a hashmap
            cache_all_keys_for_hashmap(self.hashmap)

            file_backend = LAZY_JSON_BACKENDS["file"]()

            # check if we have it in the cache first
            # if yes, load it from cache, if not load from primary backend and cache it
            if file_backend.hexists(self.hashmap, self.node):
                data_str = file_backend.hget(self.hashmap, self.node)
            else:
                backend = LAZY_JSON_BACKENDS[CF_TICK_GRAPH_DATA_PRIMARY_BACKEND]()
                backend.hsetnx(self.hashmap, self.node, dumps({}))
                data_str = backend.hget(self.hashmap, self.node)
                if isinstance(data_str, bytes):
                    data_str = data_str.decode("utf-8")
                data_str = dumps(loads(data_str))

                # cache it locally for later
                if CF_TICK_GRAPH_DATA_PRIMARY_BACKEND != "file":
                    file_backend.hset(self.hashmap, self.node, data_str)

            self._data_hash_at_load = hashlib.sha256(
                data_str.encode("utf-8"),
            ).hexdigest()
            self._data = loads(data_str)

    def _dump(self, purge=False) -> None:
        self._load()
        data_str = dumps(self._data)
        curr_hash = hashlib.sha256(data_str.encode("utf-8")).hexdigest()
        if curr_hash != self._data_hash_at_load:
            self._data_hash_at_load = curr_hash

            # cache it locally
            file_backend = LAZY_JSON_BACKENDS["file"]()
            file_backend.hset(self.hashmap, self.node, data_str)

            # sync changes to all backends
            for backend_name in CF_TICK_GRAPH_DATA_BACKENDS:
                if backend_name == "file":
                    continue
                backend = LAZY_JSON_BACKENDS[backend_name]()
                backend.hset(self.hashmap, self.node, data_str)

        if purge:
            # this evicts the josn from memory and trades i/o for mem
            # the bot uses too much mem if we don't do this
            self._data = None
            self._data_hash_at_load = None

    def sync_across_backends(self):
        """Sync data across backends."""
        self._load()
        data_str = dumps(self._data)

        # sync changes to all backends
        for backend_name in CF_TICK_GRAPH_DATA_BACKENDS:
            if backend_name == "file":
                continue
            backend = LAZY_JSON_BACKENDS[backend_name]()
            backend.hset(self.hashmap, self.node, data_str)

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
