import os
import json
import pickle
import hashlib
import subprocess

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
    sync_lazy_json_across_backends,
    make_lazy_json_backup,
    get_current_backup_filenames,
    remove_backup,
)
from conda_forge_tick.os_utils import pushd
import conda_forge_tick.utils

import pytest


def test_lazy_json_backends_backup(tmpdir):
    old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
    with pushd(tmpdir):
        try:
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = ("file",)
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                "file"
            )

            pbe = LAZY_JSON_BACKENDS["file"]()
            for hashmap in ["lazy_json", "node_attrs"]:
                for i in range(2):
                    pbe.hset(hashmap, f"node{i}", dumps({f"a{i}": i}))

            make_lazy_json_backup()

            fnames = get_current_backup_filenames()
            assert len(fnames) == 1

            subprocess.run(
                f"tar xf {fnames[0]}",
                shell=True,
                check=True,
                capture_output=True,
            )

            with pushd(fnames[0].split(".")[0]):
                for hashmap in ["lazy_json", "node_attrs"]:
                    for i in range(2):
                        pbe.hget(hashmap, f"node{i}") == dumps({f"a{i}": i})

            remove_backup(fnames[0])
            fnames = get_current_backup_filenames()
            assert len(fnames) == 0
        finally:
            be = LAZY_JSON_BACKENDS["file"]()
            for hashmap in ["lazy_json", "node_attrs"]:
                for i in range(2):
                    be.hdel(hashmap, [f"node{i}"])

            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                old_backend
            )
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                old_backend[0]
            )


@pytest.mark.parametrize(
    "backends",
    [
        ("file", "mongodb"),
        ("mongodb", "file"),
    ],
)
def test_lazy_json_backends_sync(backends, tmpdir):
    old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
    with pushd(tmpdir):
        try:
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = backends
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                backends[0]
            )

            pbe = LAZY_JSON_BACKENDS[backends[0]]()
            be = LAZY_JSON_BACKENDS[backends[1]]()

            be.hset("lazy_json", "blah", dumps({}))

            for hashmap in ["lazy_json", "node_attrs"]:
                for i in range(2):
                    pbe.hset(hashmap, f"node{i}", dumps({f"a{i}": i}))

            sync_lazy_json_across_backends()

            for hashmap in ["lazy_json", "node_attrs"]:
                for i in range(2):
                    be.hget(hashmap, f"node{i}") == dumps({f"a{i}": i})

            assert not be.hexists("lazy_json", "blah")
        finally:
            be = LAZY_JSON_BACKENDS["mongodb"]()
            for hashmap in ["lazy_json", "node_attrs"]:
                for i in range(2):
                    be.hdel(hashmap, [f"node{i}"])

            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                old_backend
            )
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                old_backend[0]
            )


@pytest.mark.parametrize("hashmap", ["lazy_json", "pr_info"])
@pytest.mark.parametrize("backend", ["file", "mongodb"])
def test_lazy_json_backends_ops(backend, hashmap, tmpdir):
    be = LAZY_JSON_BACKENDS[backend]()
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
            assert set(be.hkeys(hashmap)) == {key, key_again}

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

            with lazy_json_transaction():
                if backend == "file":
                    assert MongoDBLazyJsonBackend._session is None
                    assert MongoDBLazyJsonBackend._snapshot_session is None
                elif backend == "mongodb":
                    assert MongoDBLazyJsonBackend._session is not None
                    assert MongoDBLazyJsonBackend._snapshot_session is None

        # we test without a replica set so no snapshot session
        with lazy_json_snapshot():
            assert MongoDBLazyJsonBackend._session is None
            assert MongoDBLazyJsonBackend._snapshot_session is None

            with lazy_json_snapshot():
                assert MongoDBLazyJsonBackend._session is None
                assert MongoDBLazyJsonBackend._snapshot_session is None

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


@pytest.mark.parametrize("backend", ["file", "mongodb"])
def test_lazy_json(tmpdir, backend):
    with pushd(tmpdir):
        old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
        try:
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (backend,)
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = backend

            f = "hi.json"
            sharded_path = get_sharded_path(f)
            assert not os.path.exists(f)
            lj = LazyJson(f)
            assert not os.path.exists(lj.file_name)
            if backend == "file":
                assert os.path.exists(sharded_path)
                with open(sharded_path) as ff:
                    assert ff.read() == json.dumps({})
            else:
                assert not os.path.exists(sharded_path)

            with pytest.raises(AssertionError):
                lj.update({"hi": "globe"})
            if backend == "file":
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


def test_lazy_json_default(tmpdir):
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
