import os
import hashlib
import glob
import subprocess
import functools
import logging
import contextlib

from typing import Any, Union, Optional, IO, Set, Iterator
from collections.abc import MutableMapping, Callable

import rapidjson as json

from .cli_context import CliContext

LOGGER = logging.getLogger("conda_forge_tick.lazy_json_backends")

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
    @contextlib.contextmanager
    def transaction_context(self):
        raise NotImplementedError

    @contextlib.contextmanager
    def snapshot_context(self):
        raise NotImplementedError

    def hexists(self, name, key):
        raise NotImplementedError

    def hset(self, name, key, value):
        raise NotImplementedError

    def hmset(self, name, mapping):
        raise NotImplementedError

    def hmget(self, name, keys):
        raise NotImplementedError

    def hdel(self, name, keys):
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

    def hgetall(self, name, hashval=False):
        raise NotImplementedError


class FileLazyJsonBackend(LazyJsonBackend):
    @contextlib.contextmanager
    def transaction_context(self):
        try:
            yield self
        finally:
            pass

    @contextlib.contextmanager
    def snapshot_context(self):
        try:
            yield self
        finally:
            pass

    def hexists(self, name, key):
        return os.path.exists(get_sharded_path(f"{name}/{key}.json"))

    def hset(self, name, key, value):
        sharded_path = get_sharded_path(f"{name}/{key}.json")
        if os.path.split(sharded_path)[0]:
            os.makedirs(os.path.split(sharded_path)[0], exist_ok=True)
        with open(sharded_path, "w") as f:
            f.write(value)

    def hmset(self, name, mapping):
        for key, value in mapping.items():
            self.hset(name, key, value)

    def hmget(self, name, keys):
        return [self.hget(name, key) for key in keys]

    def hgetall(self, name, hashval=False):
        return {
            key: (
                hashlib.sha256(self.hget(name, key).encode("utf-8")).hexdigest()
                if hashval
                else self.hget(name, key)
            )
            for key in self.hkeys(name)
        }

    def hdel(self, name, keys):
        from .executors import PRLOCK, TRLOCK, DLOCK

        lzj_names = " ".join(get_sharded_path(f"{name}/{key}.json") for key in keys)
        with PRLOCK, DLOCK, TRLOCK:
            subprocess.run(
                "git rm --ignore-unmatch -f " + lzj_names,
                shell=True,
                capture_output=True,
            )
        subprocess.run(
            "rm -f " + lzj_names,
            shell=True,
            capture_output=True,
        )

    def hkeys(self, name):
        jlen = len(".json")
        if name == "lazy_json":
            fnames = glob.glob("*.json")
            fnames = set(fnames) - {
                "ranked_hubs_authorities.json",
                "all_feedstocks.json",
            }
        else:
            fnames = glob.glob(os.path.join(name, "**/*.json"), recursive=True)
        return [os.path.basename(fname)[:-jlen] for fname in fnames]

    def hget(self, name, key):
        sharded_path = get_sharded_path(f"{name}/{key}.json")
        with open(sharded_path) as f:
            data_str = f.read()
        return data_str


@functools.lru_cache(maxsize=128)
def _get_graph_data_mongodb_client_cached(pid):
    from pymongo import MongoClient
    import pymongo

    client = MongoClient(os.environ["MONGODB_CONNECTION_STRING"])

    db = client["cf_graph"]
    for hashmap in CF_TICK_GRAPH_DATA_HASHMAPS + ["lazy_json"]:
        if hashmap not in db.list_collection_names():
            coll = db.create_collection(hashmap)
            coll.create_index(
                [("node", pymongo.ASCENDING)],
                background=True,
                unique=True,
            )

    return client


def get_graph_data_mongodb_client():
    return _get_graph_data_mongodb_client_cached(str(os.getpid()))


class MongoDBLazyJsonBackend(LazyJsonBackend):
    _session = None
    _snapshot_session = None

    @contextlib.contextmanager
    def transaction_context(self):
        try:
            if self.__class__._session is None:
                client = get_graph_data_mongodb_client()
                with client.start_session() as session:
                    with session.start_transaction():
                        self.__class__._session = session
                        yield self
                        self.__class__._session = None
            else:
                yield self
        finally:
            self.__class__._session = None

    @contextlib.contextmanager
    def snapshot_context(self):
        try:
            if self.__class__._snapshot_session is None:
                client = get_graph_data_mongodb_client()
                if "Single" not in client.topology_description.topology_type_name:
                    with client.start_session(snapshot=True) as session:
                        self.__class__._snapshot_session = session
                        yield self
                        self.__class__._snapshot_session = None
                else:
                    yield self
            else:
                yield self
        finally:
            self.__class__._snapshot_session = None

    def hgetall(self, name, hashval=False):
        assert name in CF_TICK_GRAPH_DATA_HASHMAPS or name == "lazy_json"
        coll = self._get_collection(name)
        if hashval:
            curr = coll.find(
                {},
                {"node": 1, "sha256": 1},
                session=self.__class__._snapshot_session,
            )
            return {d["node"]: d["sha256"] for d in curr}
        else:
            curr = coll.find({}, session=self.__class__._snapshot_session)
            return {d["node"]: dumps(d["value"]) for d in curr}

    def _get_collection(self, name):
        return get_graph_data_mongodb_client()["cf_graph"][name]

    def hexists(self, name, key):
        assert name in CF_TICK_GRAPH_DATA_HASHMAPS or name == "lazy_json"
        coll = self._get_collection(name)
        num = coll.count_documents({"node": key}, session=self.__class__._session)
        return num == 1

    def hset(self, name, key, value):
        assert name in CF_TICK_GRAPH_DATA_HASHMAPS or name == "lazy_json"
        coll = self._get_collection(name)
        coll.update_one(
            {"node": key},
            {
                "$set": {
                    "node": key,
                    "value": json.loads(value),
                    "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                },
            },
            upsert=True,
            session=self.__class__._session,
        )

    def hmset(self, name, mapping):
        from pymongo import UpdateOne

        assert name in CF_TICK_GRAPH_DATA_HASHMAPS or name == "lazy_json"
        coll = self._get_collection(name)
        coll.bulk_write(
            [
                UpdateOne(
                    {"node": key},
                    {
                        "$set": {
                            "node": key,
                            "value": json.loads(value),
                            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
                        },
                    },
                    upsert=True,
                )
                for key, value in mapping.items()
            ],
            session=self.__class__._session,
        )

    def hmget(self, name, keys):
        assert name in CF_TICK_GRAPH_DATA_HASHMAPS or name == "lazy_json"
        coll = self._get_collection(name)
        cur = coll.find(
            {"node": {"$in": list(keys)}},
            session=self.__class__._session,
        )
        odata = {d["node"]: dumps(d["value"]) for d in cur}
        return [odata[k] for k in keys]

    def hdel(self, name, keys):
        assert name in CF_TICK_GRAPH_DATA_HASHMAPS or name == "lazy_json"
        coll = self._get_collection(name)
        for key in keys:
            coll.delete_one({"node": key}, session=self.__class__._session)

    def hkeys(self, name):
        assert name in CF_TICK_GRAPH_DATA_HASHMAPS or name == "lazy_json"
        coll = self._get_collection(name)
        curr = coll.find({}, {"node": 1}, session=self.__class__._session)
        return [doc["node"] for doc in curr]

    def hget(self, name, key):
        assert name in CF_TICK_GRAPH_DATA_HASHMAPS or name == "lazy_json"
        coll = self._get_collection(name)
        data = coll.find_one({"node": key}, session=self.__class__._session)
        assert data is not None
        return dumps(data["value"])


LAZY_JSON_BACKENDS = {
    "file": FileLazyJsonBackend,
    "mongodb": MongoDBLazyJsonBackend,
}


def sync_lazy_json_hashmap(
    hashmap,
    source_backend,
    destination_backends,
    n_per_batch=5000,
    writer=print,
):
    primary_backend = LAZY_JSON_BACKENDS[source_backend]()
    primary_hashes = primary_backend.hgetall(hashmap, hashval=True)
    primary_nodes = set(primary_hashes.keys())
    writer(
        "    FOUND %s:%s nodes (%d)" % (source_backend, hashmap, len(primary_nodes)),
    )

    all_nodes_to_get = set()
    backend_hashes = {}
    for backend_name in destination_backends:
        backend = LAZY_JSON_BACKENDS[backend_name]()
        backend_hashes[backend_name] = backend.hgetall(hashmap, hashval=True)
        writer(
            "    FOUND %s:%s nodes (%d)"
            % (backend_name, hashmap, len(backend_hashes[backend_name])),
        )

        curr_nodes = set(backend_hashes[backend_name].keys())
        del_nodes = curr_nodes - primary_nodes
        if del_nodes:
            backend.hdel(hashmap, list(del_nodes))
            writer(
                "    DELETED %s:%s nodes (%d): %r"
                % (backend_name, hashmap, len(del_nodes), sorted(del_nodes)),
            )

        for node, hashval in primary_hashes.items():
            if node not in backend_hashes[backend_name] or (
                backend_hashes[backend_name][node] != primary_hashes[node]
            ):
                all_nodes_to_get.add(node)

    writer(
        "    OUT OF SYNC %s:%s nodes (%d)"
        % (source_backend, hashmap, len(all_nodes_to_get)),
    )

    while all_nodes_to_get:
        nodes_to_get = [
            all_nodes_to_get.pop()
            for _ in range(min(len(all_nodes_to_get), n_per_batch))
        ]
        writer(
            "    PULLING %s:%s nodes (%d) for batch"
            % (source_backend, hashmap, len(nodes_to_get)),
        )

        batch = {
            k: v
            for k, v in zip(
                nodes_to_get,
                primary_backend.hmget(hashmap, nodes_to_get),
            )
        }
        for backend_name in destination_backends:
            _batch = {
                node: value
                for node, value in batch.items()
                if (
                    node not in backend_hashes[backend_name]
                    or (backend_hashes[backend_name][node] != primary_hashes[node])
                )
            }
            if _batch:
                writer(
                    "    UPDATING %s:%s nodes (%d)"
                    % (backend_name, hashmap, len(_batch)),
                )

                backend = LAZY_JSON_BACKENDS[backend_name]()
                backend.hmset(hashmap, _batch)
                writer(
                    "    UPDATED %s:%s nodes (%d): %r"
                    % (backend_name, hashmap, len(_batch), sorted(_batch)),
                )


def sync_lazy_json_across_backends(batch_size=5000):
    """Sync data from the primary backend to the secondary ones.

    If there is only one backend, this is a no-op.
    """
    if len(CF_TICK_GRAPH_DATA_BACKENDS) > 1:
        # pulling in this order helps us ensure we get a consistent view
        # of the backend data even if we did not sync from a snapshot
        all_collections = set(CF_TICK_GRAPH_DATA_HASHMAPS + ["lazy_json"])
        ordered_collections = [
            "lazy_json",
            "node_attrs",
            "pr_info",
            "version_pr_info",
            "pr_json",
            "versions",
        ]
        rest_of_the_collections = list(all_collections - set(ordered_collections))

        def _write_and_flush(x):
            print(x, flush=True)

        for hashmap in ordered_collections + rest_of_the_collections:
            print("SYNCING %s" % hashmap, flush=True)
            sync_lazy_json_hashmap(
                hashmap,
                CF_TICK_GRAPH_DATA_PRIMARY_BACKEND,
                CF_TICK_GRAPH_DATA_BACKENDS[1:],
                writer=_write_and_flush,
            )

        # if mongodb has better performance we do this
        # only certain collections need to be updated in a single transaction
        # all_collections = set(CF_TICK_GRAPH_DATA_HASHMAPS + ["lazy_json"])
        # pr_collections = {"pr_info", "pr_json", "version_pr_info"}
        # node_collections = {"node_attrs", "lazy_json"}
        # parallel_collections = all_collections - pr_collections - node_collections

        # for collection_set in [pr_collections, node_collections]:
        #     with primary_backend.snapshot_context():
        #         with tqdm.tqdm(
        #             collection_set,
        #             ncols=80,
        #             desc="syncing %r" % collection_set,
        #         ) as pbar:
        #             for hashmap in pbar:
        #                 tqdm.tqdm.write("SYNCING %s" % hashmap)
        #                 _flush_it()
        #                 _sync_hashmap(hashmap, batch_size, primary_backend)

        # with tqdm.tqdm(
        #     parallel_collections,
        #     ncols=80,
        #     desc="syncing %r" % parallel_collections,
        # ) as pbar:
        #     for hashmap in pbar:
        #         tqdm.tqdm.write("SYNCING %s" % hashmap)
        #         _flush_it()
        #         _sync_hashmap(hashmap, batch_size, primary_backend)


def remove_key_for_hashmap(name, node):
    """Remove the key node for hashmap name."""
    for backend_name in CF_TICK_GRAPH_DATA_BACKENDS:
        backend = LAZY_JSON_BACKENDS[backend_name]()
        backend.hdel(name, [node])


def get_all_keys_for_hashmap(name):
    """Get all keys for the hashmap `name`."""
    backend = LAZY_JSON_BACKENDS[CF_TICK_GRAPH_DATA_PRIMARY_BACKEND]()
    return backend.hkeys(name)


@contextlib.contextmanager
def lazy_json_transaction():
    try:
        backend = LAZY_JSON_BACKENDS[CF_TICK_GRAPH_DATA_PRIMARY_BACKEND]()
        with backend.transaction_context():
            yield None
    finally:
        pass


@contextlib.contextmanager
def lazy_json_snapshot():
    try:
        backend = LAZY_JSON_BACKENDS[CF_TICK_GRAPH_DATA_PRIMARY_BACKEND]()
        with backend.snapshot_context():
            yield None
    finally:
        pass


@contextlib.contextmanager
def lazy_json_override_backends(new_backends, hashmaps_to_sync=None):
    global CF_TICK_GRAPH_DATA_BACKENDS
    global CF_TICK_GRAPH_DATA_PRIMARY_BACKEND

    old_backends = CF_TICK_GRAPH_DATA_BACKENDS
    try:
        CF_TICK_GRAPH_DATA_BACKENDS = tuple(new_backends)
        CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = new_backends[0]
        yield
    finally:
        if hashmaps_to_sync is not None:
            sync_backends = list(set(old_backends) - set(new_backends))
            if sync_backends:
                for hashmap in hashmaps_to_sync:
                    print(
                        f"SYNCING {hashmap} from {new_backends[0]} to {sync_backends}",
                        flush=True,
                    )
                    sync_lazy_json_hashmap(
                        hashmap,
                        new_backends[0],
                        sync_backends,
                    )

        CF_TICK_GRAPH_DATA_BACKENDS = old_backends
        CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = old_backends[0]


def get_lazy_json_backends():
    return CF_TICK_GRAPH_DATA_BACKENDS


def get_lazy_json_primary_backend():
    return CF_TICK_GRAPH_DATA_PRIMARY_BACKEND


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


def main_sync(ctx: CliContext = CliContext()):
    from conda_forge_tick.utils import setup_logger

    if ctx.debug:
        setup_logger(logging.getLogger("conda_forge_tick"), level="debug")
    else:
        setup_logger(logging.getLogger("conda_forge_tick"))

    if not ctx.dry_run:
        sync_lazy_json_across_backends()


def main_cache(ctx: CliContext = CliContext()):
    from conda_forge_tick.utils import setup_logger

    global CF_TICK_GRAPH_DATA_BACKENDS

    if ctx.debug:
        setup_logger(logging.getLogger("conda_forge_tick"), level="debug")
    else:
        setup_logger(logging.getLogger("conda_forge_tick"))

    if not ctx.dry_run and len(CF_TICK_GRAPH_DATA_BACKENDS) > 1:
        OLD_CF_TICK_GRAPH_DATA_BACKENDS = CF_TICK_GRAPH_DATA_BACKENDS
        try:
            CF_TICK_GRAPH_DATA_BACKENDS = (
                CF_TICK_GRAPH_DATA_PRIMARY_BACKEND,
                "file",
            )
            sync_lazy_json_across_backends()
        finally:
            CF_TICK_GRAPH_DATA_BACKENDS = OLD_CF_TICK_GRAPH_DATA_BACKENDS
