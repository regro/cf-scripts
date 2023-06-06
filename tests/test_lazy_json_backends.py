import os
import json
import pickle
import hashlib

from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    dumps,
    loads,
    load,
    dump,
    get_sharded_path,
    get_all_keys_for_hashmap,
    remove_key_for_hashmap,
    lazy_json_snapshot,
    lazy_json_transaction,
    MongoDBLazyJsonBackend,
    LAZY_JSON_BACKENDS,
)
from conda_forge_tick.os_utils import pushd
import conda_forge_tick.utils

import pytest


@pytest.mark.parametrize("backend", ["file", "mongodb"])
def test_lazy_json_backends_ops(backend, tmpdir):
    be = LAZY_JSON_BACKENDS[backend]()
    hashmap = "pr_info"
    key = "blah"
    value = dumps({"a": 1, "b": 2})
    key_again = "blahblah"
    value_again = dumps({"a": 1, "b": 2, "c": 3})

    with pushd(tmpdir):
        try:
            assert not be.hexists(hashmap, key)
            assert be.hkeys(hashmap) == []

            be.hset(hashmap, key, value)
            assert be.hget(hashmap, key) == value
            assert be.hexists(hashmap, key)
            assert be.hkeys(hashmap) == [key]

            assert not be.hsetnx(hashmap, key, dumps({}))
            assert be.hget(hashmap, key) == value

            be.hdel(hashmap, [key])
            assert not be.hexists(hashmap, key)
            assert be.hkeys(hashmap) == []

            assert be.hsetnx(hashmap, key, value)
            assert be.hget(hashmap, key) == value
            assert be.hexists(hashmap, key)
            assert be.hkeys(hashmap) == [key]

            be.hdel(hashmap, [key])
            assert not be.hexists(hashmap, key)
            assert be.hkeys(hashmap) == []

            mapping = {key: value, key_again: value_again}
            be.hmset(hashmap, mapping)
            assert be.hget(hashmap, key) == value
            assert be.hget(hashmap, key_again) == value_again
            assert be.hexists(hashmap, key)
            assert be.hexists(hashmap, key_again)
            assert be.hkeys(hashmap) == [key, key_again]

            assert be.hmget(hashmap, [key, key_again]) == [value, value_again]
            assert be.hmget(hashmap, [key_again, key]) == [value_again, value]

            assert be.hgetall(hashmap) == mapping

            assert be.hgetall(hashmap, hashval=True) == {
                key: hashlib.sha256(value.encode("utf-8")).hexdigest(),
                key_again: hashlib.sha256(value_again.encode("utf-8")).hexdigest(),
            }
        finally:
            be.hdel(hashmap, [key, key_again])


@pytest.mark.parametrize("backend", ["file", "mongodb"])
def test_lazy_json_backends_contexts(backend):
    old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
    try:
        conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (backend,)
        conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = backend

        with lazy_json_transaction():
            if backend == "file":
                assert MongoDBLazyJsonBackend._session is None
                assert MongoDBLazyJsonBackend._snapshot_session is None
            elif backend == "mongodb":
                assert MongoDBLazyJsonBackend._session is not None
                assert MongoDBLazyJsonBackend._snapshot_session is None

        with lazy_json_snapshot():
            if backend == "file":
                assert MongoDBLazyJsonBackend._session is None
                assert MongoDBLazyJsonBackend._snapshot_session is None
            elif backend == "mongodb":
                assert MongoDBLazyJsonBackend._session is None
                assert MongoDBLazyJsonBackend._snapshot_session is not None

    finally:
        conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = old_backend
        conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
            old_backend[0]
        )


def test_lazy_json_backends_dump_load(tmpdir):
    with pushd(tmpdir):
        blob = {"c": "3333", "a": {1, 2, 3}, "b": 56, "d": LazyJson("blah.json")}

        assert blob == loads(dumps(blob))
        assert (
            dumps(blob)
            == """\
{
 "a": {
  "__set__": true,
  "elements": [
   1,
   2,
   3
  ]
 },
 "b": 56,
 "c": "3333",
 "d": {
  "__lazy_json__": "blah.json"
 }
}"""
        )

        with open(os.path.join(tmpdir, "blah"), "w") as fp:
            dump(blob, fp)

        with open(os.path.join(tmpdir, "blah")) as fp:
            assert load(fp) == blob

        class Blah:
            pass

        with pytest.raises(TypeError):
            dumps({"a": Blah()})


def test_lazy_json_file(tmpdir):
    old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
    try:
        conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = ("file",)
        conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = "file"

        f = os.path.join(tmpdir, "hi.json")
        sharded_path = get_sharded_path(f)
        assert not os.path.exists(f)
        lj = LazyJson(f)
        assert not os.path.exists(lj.file_name)
        assert os.path.exists(sharded_path)
        with open(sharded_path) as ff:
            assert ff.read() == json.dumps({})

        with pytest.raises(AssertionError):
            lj.update({"hi": "globe"})
        with open(sharded_path) as ff:
            assert ff.read() == dumps({})
        p = pickle.dumps(lj)
        lj2 = pickle.loads(p)
        assert not getattr(lj2, "_data", None)

        with lj as attrs:
            attrs["hi"] = "world"
        assert lj["hi"] == "world"
        assert os.path.exists(sharded_path)
        with open(sharded_path) as ff:
            assert ff.read() == dumps({"hi": "world"})

        with lj as attrs:
            attrs.update({"hi": "globe"})
            attrs.setdefault("lst", []).append("universe")
        with open(sharded_path) as ff:
            assert ff.read() == dumps({"hi": "globe", "lst": ["universe"]})

        with lj as attrs:
            attrs.setdefault("lst", []).append("universe")
            with lj as attrs_again:
                attrs_again.setdefault("lst", []).append("universe")
                attrs.setdefault("lst", []).append("universe")
        with open(sharded_path) as ff:
            assert ff.read() == dumps({"hi": "globe", "lst": ["universe"] * 4})

        with lj as attrs:
            with lj as attrs_again:
                attrs_again.setdefault("lst2", []).append("universe")
                attrs.setdefault("lst2", []).append("universe")
        with open(sharded_path) as ff:
            assert ff.read() == dumps(
                {"hi": "globe", "lst": ["universe"] * 4, "lst2": ["universe"] * 2},
            )

        with lj as attrs:
            del attrs["lst"]
        with open(sharded_path) as ff:
            assert ff.read() == dumps(
                {"hi": "globe", "lst2": ["universe"] * 2},
            )

        with lj as attrs:
            attrs.pop("lst2")
        with open(sharded_path) as ff:
            assert ff.read() == dumps({"hi": "globe"})

        assert len(lj) == 1
        assert {k for k in lj} == {"hi"}

        with lj as attrs:
            attrs.clear()
        with open(sharded_path) as ff:
            assert ff.read() == dumps({})
        assert len(lj) == 0
        assert not lj
    finally:
        conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = old_backend
        conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
            old_backend[0]
        )


def test_lazy_json(tmpdir):
    with pushd(str(tmpdir)):
        f = "hi.json"
        fpth = get_sharded_path(f)
        assert fpth == f
        assert not os.path.exists(fpth)
        lj = LazyJson(f)
        assert os.path.exists(lj.file_name)
        assert os.path.exists(fpth)

        with open(fpth) as ff:
            assert ff.read() == json.dumps({})

        with pytest.raises(AssertionError):
            lj.update({"hi": "globe"})

        p = pickle.dumps(lj)
        lj2 = pickle.loads(p)
        assert not getattr(lj2, "_data", None)

        with lj as attrs:
            attrs.setdefault("lst", []).append("universe")
        with open(fpth) as ff:
            assert ff.read() == dumps({"lst": ["universe"]})

        with lj as attrs:
            attrs.setdefault("lst", []).append("universe")
            with lj as attrs_again:
                attrs_again.setdefault("lst", []).append("universe")
                attrs.setdefault("lst", []).append("universe")
        with open(fpth) as ff:
            assert ff.read() == dumps({"lst": ["universe"] * 4})

        with lj as attrs:
            with lj as attrs_again:
                attrs_again.setdefault("lst2", []).append("universe")
                attrs.setdefault("lst2", []).append("universe")
        with open(fpth) as ff:
            assert ff.read() == dumps(
                {"lst": ["universe"] * 4, "lst2": ["universe"] * 2},
            )

        with lj as attrs:
            del attrs["lst"]
        with open(fpth) as ff:
            assert ff.read() == dumps(
                {"lst2": ["universe"] * 2},
            )

        with lj as attrs:
            attrs.pop("lst2")
        with open(fpth) as ff:
            assert ff.read() == dumps({})

        with lj as attrs:
            attrs["hi"] = "world"

        with pytest.raises(AssertionError):
            lj["hi"] = "worldz"

        assert lj.data == {"hi": "world"}
        assert lj["hi"] == "world"

        assert len(lj) == 1
        assert {k for k in lj} == {"hi"}

        with pytest.raises(AssertionError):
            lj.clear()
        with lj as attrs:
            attrs.clear()
        with open(fpth) as ff:
            assert ff.read() == dumps({})


def test_lazy_json_backends_hashmap(tmpdir):
    with pushd(tmpdir):
        LazyJson("blah.json")
        LazyJson("node_attrs/blah.json")
        LazyJson("node_attrs/blah_blah.json")

        assert get_all_keys_for_hashmap("lazy_json") == ["blah"]
        assert sorted(get_all_keys_for_hashmap("node_attrs")) == sorted(
            ["blah", "blah_blah"],
        )
        remove_key_for_hashmap("node_attrs", "blah")
        assert sorted(get_all_keys_for_hashmap("node_attrs")) == sorted(["blah_blah"])
        assert get_all_keys_for_hashmap("lazy_json") == ["blah"]
        remove_key_for_hashmap("lazy_json", "blah")
        assert get_all_keys_for_hashmap("lazy_json") == []
