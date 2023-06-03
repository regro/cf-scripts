import os
import hashlib
import glob
import subprocess
import tqdm
import functools
import shutil
import datetime
import pprint
import logging
import contextlib

from typing import Any, Union, Optional, IO, Set, Iterator
from collections.abc import MutableMapping, Callable

import rapidjson as json

from conda_forge_tick.os_utils import pushd

LOGGER = logging.getLogger("conda_forge_tick.lazy_json_backends")


CF_TICK_GRAPH_DATA_BACKUP_BACKEND = os.environ.get(
    "CF_TICK_GRAPH_DATA_BACKUP_BACKEND",
    "file",
)

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

    def unload_to_disk(self, name):
        raise NotImplementedError

    def hexists(self, name, key):
        raise NotImplementedError

    def hset(self, name, key, value):
        raise NotImplementedError

    def hmset(self, name, mapping):
        raise NotImplementedError

    def hmget(self, name, keys):
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

    def hmset(self, name, mapping):
        for key, value in mapping.items():
            self.hset(name, key, value)

    def hmget(self, name, keys):
        return [self.hget(name, key) for key in keys]

    def hdel(self, name, keys):
        from .executors import PRLOCK, TRLOCK, DLOCK

        lzj_names = " ".join(get_sharded_path(f"{name}/{key}.json") for key in keys)
        with PRLOCK, DLOCK, TRLOCK:
            try:
                res = subprocess.run(
                    "git rm -f " + lzj_names,
                    shell=True,
                    capture_output=True,
                )
                if res.returncode != 0:
                    raise RuntimeError(
                        res.stdout.decode("utf-8") + res.stderr.decode("utf-8"),
                    )
            except Exception as e:
                if "not a git repository" not in str(e):
                    raise e
        subprocess.run(
            "rm -f " + lzj_names,
            shell=True,
            check=True,
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
            pass

    @contextlib.contextmanager
    def snapshot_context(self):
        try:
            if self.__class__._snapshot_session is None:
                client = get_graph_data_mongodb_client()
                with client.start_session(snapshot=True) as session:
                    self.__class__._snapshot_session = session
                    yield self
                    self.__class__._snapshot_session = None
            else:
                yield self
        finally:
            pass

    def unload_to_disk(self, name):
        from pymongo import ReadPreference

        col = self._get_collection(name)
        col = col.with_options(read_preference=ReadPreference.PRIMARY_PREFERRED)
        ntot = col.count_documents({}, session=self.__class__._snapshot_session)
        curr = col.find({}, session=self.__class__._snapshot_session)
        print("\n\n" + ">" * 80, flush=True)
        print(">" * 80, flush=True)
        for d in tqdm.tqdm(curr, ncols=80, total=ntot, desc="caching %s" % name):
            fname = get_sharded_path(name + "/" + d["node"] + ".json")
            if os.path.split(fname)[0]:
                os.makedirs(os.path.split(fname)[0], exist_ok=True)
            with open(fname, "w") as fp:
                dump(d["value"], fp)
        print(">" * 80, flush=True)
        print(">" * 80 + "\n\n", flush=True)

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
        coll = self._get_collection()
        data = coll.find_one({"node": key}, session=self.__class__._session)
        assert data is not None
        return dumps(data["value"])


LAZY_JSON_BACKENDS = {
    "file": FileLazyJsonBackend,
    "mongodb": MongoDBLazyJsonBackend,
}


def sync_lazy_json_across_backends(batch_size=5000):
    """Sync data from the primary backend to the secondary ones.

    If there is only one backend, this is a no-op.
    """

    def _sync_hashmap(hashmap, n_per_batch, primary_backend):
        primary_nodes = set(get_all_keys_for_hashmap(hashmap))

        for backend_name in CF_TICK_GRAPH_DATA_BACKENDS[1:]:
            backend = LAZY_JSON_BACKENDS[backend_name]()
            curr_nodes = set(backend.hkeys(hashmap))
            del_nodes = curr_nodes - primary_nodes
            if del_nodes:
                backend.hdel(hashmap, list(del_nodes))

        nodes_to_get = []
        for node in tqdm.tqdm(primary_nodes, desc=f"syncing {hashmap}", ncols=80):
            if len(nodes_to_get) < n_per_batch:
                nodes_to_get.append(node)
            else:
                batch = {
                    k: v
                    for k, v in zip(
                        nodes_to_get,
                        primary_backend.hmget(hashmap, nodes_to_get),
                    )
                }
                nodes_to_get = []
                for backend_name in CF_TICK_GRAPH_DATA_BACKENDS[1:]:
                    backend = LAZY_JSON_BACKENDS[backend_name]()
                    backend.hmset(hashmap, batch)

        if nodes_to_get:
            batch = {
                k: v
                for k, v in zip(
                    nodes_to_get,
                    primary_backend.hmget(hashmap, nodes_to_get),
                )
            }
            nodes_to_get = []
            for backend_name in CF_TICK_GRAPH_DATA_BACKENDS[1:]:
                backend = LAZY_JSON_BACKENDS[backend_name]()
                backend.hmset(hashmap, batch)

    if len(CF_TICK_GRAPH_DATA_BACKENDS) > 1:
        primary_backend = LAZY_JSON_BACKENDS[CF_TICK_GRAPH_DATA_PRIMARY_BACKEND]()
        with primary_backend.snapshot_context():
            for hashmap in tqdm.tqdm(
                CF_TICK_GRAPH_DATA_HASHMAPS + ["lazy_json"],
                ncols=80,
                desc="syncing hashmaps",
            ):
                _sync_hashmap(hashmap, batch_size, primary_backend)


def cache_lazy_json_to_disk(dest_dir="."):
    from conda_forge_tick.executors import PRLOCK, TRLOCK, DLOCK

    backend = LAZY_JSON_BACKENDS[CF_TICK_GRAPH_DATA_PRIMARY_BACKEND]()

    os.makedirs(dest_dir, exist_ok=True)

    with PRLOCK, TRLOCK, DLOCK, backend.snapshot_context():
        for hashmap in CF_TICK_GRAPH_DATA_HASHMAPS + ["lazy_json"]:
            if CF_TICK_GRAPH_DATA_PRIMARY_BACKEND != "file":
                with pushd(dest_dir):
                    backend.unload_to_disk(hashmap)
            else:
                if hashmap == "lazy_json":
                    nodes = backend.hkeys("lazy_json")
                    for node in nodes:
                        shutil.copy2(node + ".json", dest_dir)
                else:
                    shutil.copytree(hashmap, os.path.join(dest_dir, hashmap))


def make_lazy_json_backup():
    ts = str(int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp()))
    try:
        dest_dir = f"backups/cf_graph_{ts}"
        os.makedirs(dest_dir, exist_ok=True)
        LOGGER.info("caching lazy json to disk")
        cache_lazy_json_to_disk(dest_dir=dest_dir)
        LOGGER.info("compressing lazy json disk cache")
        subprocess.run(
            f"cd backups && tar --zstd -cvf cf_graph_{ts}.tar.zstd cf_graph_{ts}",
            shell=True,
            check=True,
            capture_output=True,
        )
    finally:
        LOGGER.info("removing uncompressed lazy json")
        shutil.rmtree(dest_dir, ignore_errors=True)

    return f"cf_graph_{ts}.tar.zstd"


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


def prune_timestamps(
    timestamps,
    maxsize=4000,
    sizeper=50,
    nhours=24,
    ndays=7,
    nweeks=8,
    nmonths=24,
):
    tokeep = {}

    one_hour = datetime.timedelta(hours=1)
    one_day = datetime.timedelta(days=1)
    one_week = datetime.timedelta(weeks=1)
    one_month = datetime.timedelta(weeks=4)

    now = datetime.datetime.now(tz=datetime.timezone.utc)

    tot = 0
    for ts in sorted(timestamps)[::-1]:
        dt = datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc)
        for i in range(nhours):
            key = f"h{i}"
            dt_high = now - i * one_hour
            dt_low = dt_high - one_hour
            if dt >= dt_low and dt <= dt_high and key not in tokeep and tot < maxsize:
                tokeep[key] = int(ts)
                tot = len(set(tokeep.values())) * sizeper
                break

        for i in range(ndays):
            key = f"d{i}"
            dt_high = now - i * one_day
            dt_low = dt_high - one_day
            if dt >= dt_low and dt <= dt_high and key not in tokeep and tot < maxsize:
                tokeep[key] = int(ts)
                tot = len(set(tokeep.values())) * sizeper
                break

        for i in range(nweeks):
            key = f"w{i}"
            dt_high = now - i * one_week
            dt_low = dt_high - one_week
            if dt >= dt_low and dt <= dt_high and key not in tokeep and tot < maxsize:
                tokeep[key] = int(ts)
                tot = len(set(tokeep.values())) * sizeper
                break

        for i in range(nmonths):
            key = f"m{i}"
            dt_high = now - i * one_month
            dt_low = dt_high - one_month
            if dt >= dt_low and dt <= dt_high and key not in tokeep and tot < maxsize:
                tokeep[key] = int(ts)
                tot = len(set(tokeep.values())) * sizeper
                break

    if len(tokeep) == 0 and len(ts) > 0:
        tokeep["keep_one"] = int(sorted(timestamps)[::-1][0])

    return tokeep


def get_current_backup_filenames():
    if CF_TICK_GRAPH_DATA_BACKUP_BACKEND == "file":
        backups = glob.glob("backups/*.tar.zstd")
        return [os.path.basename(b) for b in backups]
    else:
        raise RuntimeError(
            "CF_TICK_GRAPH_DATA_BACKUP_BACKEND %s not recognized!"
            % CF_TICK_GRAPH_DATA_BACKUP_BACKEND,
        )


def remove_backup(fname):
    if CF_TICK_GRAPH_DATA_BACKUP_BACKEND == "file":
        try:
            os.remove(f"backups/{fname}")
        except Exception:
            pass
    else:
        raise RuntimeError(
            "CF_TICK_GRAPH_DATA_BACKUP_BACKEND %s not recognized!"
            % CF_TICK_GRAPH_DATA_BACKUP_BACKEND,
        )


def save_backup(fname):
    if CF_TICK_GRAPH_DATA_BACKUP_BACKEND == "file":
        pass
    else:
        raise RuntimeError(
            "CF_TICK_GRAPH_DATA_BACKUP_BACKEND %s not recognized!"
            % CF_TICK_GRAPH_DATA_BACKUP_BACKEND,
        )


def main_backup(args):
    from conda_forge_tick.utils import setup_logger

    if args.debug:
        setup_logger(logging.getLogger("conda_forge_tick"), level="debug")
    else:
        setup_logger(logging.getLogger("conda_forge_tick"))

    def _name_to_ts(b):
        return int(b.split(".")[0].split("_")[-1])

    if not args.dry_run:
        os.makedirs("backups", exist_ok=True)
        LOGGER.info("making lazy json backup")
        latest_backup = make_lazy_json_backup()
        curr_fnames = get_current_backup_filenames()
        all_fnames = set(curr_fnames) | {latest_backup}
        all_timestamps = [_name_to_ts(b) for b in all_fnames]
        tsdict = prune_timestamps(all_timestamps)
        LOGGER.info("backups to keep:\n%s", pprint.pformat(tsdict, sort_dicts=False))

        timestamps_to_keep = set(tsdict.values())
        for bup in all_fnames:
            if _name_to_ts(bup) not in timestamps_to_keep:
                try:
                    LOGGER.info("removing backup %s", bup)
                    remove_backup(bup)
                except Exception:
                    pass
            else:
                LOGGER.info("saving backup %s", bup)
                if bup not in curr_fnames:
                    save_backup(bup)


def main_sync(args):
    from conda_forge_tick.utils import setup_logger

    if args.debug:
        setup_logger(logging.getLogger("conda_forge_tick"), level="debug")
    else:
        setup_logger(logging.getLogger("conda_forge_tick"))

    if not args.dry_run:
        sync_lazy_json_across_backends()


def main_cache(args):
    from conda_forge_tick.utils import setup_logger

    if args.debug:
        setup_logger(logging.getLogger("conda_forge_tick"), level="debug")
    else:
        setup_logger(logging.getLogger("conda_forge_tick"))

    if not args.dry_run:
        cache_lazy_json_to_disk()
