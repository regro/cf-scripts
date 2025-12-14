import base64
import hashlib
import json
import logging
import os
import pickle
import tempfile
import time
import uuid
from unittest import mock
from unittest.mock import MagicMock

import pytest

import conda_forge_tick
from conda_forge_tick.git_utils import github_client
from conda_forge_tick.lazy_json_backends import (
    LAZY_JSON_BACKENDS,
    GithubLazyJsonBackend,
    LazyJson,
    MongoDBLazyJsonBackend,
    dump,
    dumps,
    get_all_keys_for_hashmap,
    get_lazy_json_backends,
    get_lazy_json_primary_backend,
    get_sharded_path,
    lazy_json_override_backends,
    lazy_json_snapshot,
    lazy_json_transaction,
    load,
    loads,
    remove_key_for_hashmap,
    sync_lazy_json_across_backends,
    touch_all_lazy_json_refs,
)
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.settings import settings

HAVE_MONGODB = (
    "MONGODB_CONNECTION_STRING" in conda_forge_tick.global_sensitive_env.classified_info
    and conda_forge_tick.global_sensitive_env.classified_info[
        "MONGODB_CONNECTION_STRING"
    ]
    is not None
)


@pytest.mark.skipif(not HAVE_MONGODB, reason="no mongodb")
@pytest.mark.mongodb
def test_lazy_json_override_backends_global(tmpdir):
    old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
    with pushd(tmpdir):
        try:
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                "mongodb",
                "file",
            )
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                "mongodb"
            )

            lzj = LazyJson("blah.json")
            with lzj as attrs:
                attrs["hello"] = "world"
            pbe = LAZY_JSON_BACKENDS["mongodb"]()
            be = LAZY_JSON_BACKENDS["file"]()

            assert be.hget("lazy_json", "blah") == pbe.hget("lazy_json", "blah")
            assert be.hget("lazy_json", "blah") == dumps({"hello": "world"})

            with lazy_json_override_backends(["file"]):
                assert (
                    conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
                    == ("file",)
                )
                assert (
                    conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND
                    == "file"
                )
                assert get_lazy_json_backends() == ("file",)
                assert get_lazy_json_primary_backend() == "file"
                with lzj as attrs:
                    attrs["hello"] = "me"

            assert be.hget("lazy_json", "blah") != pbe.hget("lazy_json", "blah")
            assert be.hget("lazy_json", "blah") == dumps({"hello": "me"})

            assert conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS == (
                "mongodb",
                "file",
            )
            assert (
                conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND
                == "mongodb"
            )
            assert get_lazy_json_backends() == (
                "mongodb",
                "file",
            )
            assert get_lazy_json_primary_backend() == "mongodb"

            with lazy_json_override_backends(["file"], hashmaps_to_sync=["lazy_json"]):
                assert (
                    conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
                    == ("file",)
                )
                assert (
                    conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND
                    == "file"
                )
                assert get_lazy_json_backends() == ("file",)
                assert get_lazy_json_primary_backend() == "file"
                with lzj as attrs:
                    attrs["hello"] = "me again"

            assert be.hget("lazy_json", "blah") == pbe.hget("lazy_json", "blah")
            assert be.hget("lazy_json", "blah") == dumps({"hello": "me again"})

            with lazy_json_override_backends(
                ["file"], hashmaps_to_sync=["lazy_json"], keys_to_sync=set()
            ):
                assert (
                    conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
                    == ("file",)
                )
                assert (
                    conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND
                    == "file"
                )
                assert get_lazy_json_backends() == ("file",)
                assert get_lazy_json_primary_backend() == "file"
                with lzj as attrs:
                    attrs["hello"] = "me again again"

            assert be.hget("lazy_json", "blah") != pbe.hget("lazy_json", "blah")
            assert be.hget("lazy_json", "blah") == dumps({"hello": "me again again"})

        finally:
            be = LAZY_JSON_BACKENDS["mongodb"]()
            be.hdel("lazy_json", ["blah"])

            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                old_backend
            )
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                old_backend[0]
            )


@pytest.mark.skipif(not HAVE_MONGODB, reason="no mongodb")
@pytest.mark.mongodb
def test_lazy_json_override_backends_global_nocache(tmpdir):
    old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
    with pushd(tmpdir):
        try:
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                "mongodb",
            )
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                "mongodb"
            )

            lzj = LazyJson("blah.json")
            with lzj as attrs:
                attrs["hello"] = "world"
            pbe = LAZY_JSON_BACKENDS["mongodb"]()
            be = LAZY_JSON_BACKENDS["file"]()

            assert be.hget("lazy_json", "blah") == pbe.hget("lazy_json", "blah")
            assert be.hget("lazy_json", "blah") == dumps({"hello": "world"})

            with lazy_json_override_backends(["mongodb"], use_file_cache=False):
                assert (
                    conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
                    == ("mongodb",)
                )
                assert (
                    conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND
                    == "mongodb"
                )
                used_cache = getattr(
                    conda_forge_tick.lazy_json_backends,
                    "CF_TICK_GRAPH_DATA_USE_FILE_CACHE",
                )
                assert not used_cache
                assert get_lazy_json_backends() == ("mongodb",)
                assert get_lazy_json_primary_backend() == "mongodb"
                lzj = LazyJson("blah2.json")
                with lzj as attrs:
                    attrs["hello"] = "world"

                assert not be.hexists("lazy_json", "blah2")
                assert be.hexists("lazy_json", "blah")
                assert pbe.hexists("lazy_json", "blah")
        finally:
            for bename in ["file", "mongodb"]:
                for key in ["blah", "blah2"]:
                    be = LAZY_JSON_BACKENDS[bename]()
                    if be.hexists("lazy_json", key):
                        be.hdel("lazy_json", [key])

            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                old_backend
            )
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                old_backend[0]
            )


@pytest.mark.skipif(not HAVE_MONGODB, reason="no mongodb")
@pytest.mark.parametrize(
    "backends",
    [
        ("file", "mongodb"),
        ("mongodb", "file"),
    ],
)
@pytest.mark.mongodb
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
@pytest.mark.parametrize(
    "backend",
    [
        "file",
        pytest.param(
            "mongodb",
            marks=[
                pytest.mark.skipif(
                    not HAVE_MONGODB,
                    reason="no mongodb",
                ),
                pytest.mark.mongodb,
            ],
        ),
    ],
)
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


@pytest.mark.parametrize(
    "backend",
    [
        "file",
        pytest.param(
            "mongodb",
            marks=[
                pytest.mark.skipif(
                    not HAVE_MONGODB,
                    reason="no mongodb",
                ),
                pytest.mark.mongodb,
            ],
        ),
    ],
)
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


@pytest.mark.parametrize(
    "backend",
    [
        "file",
        pytest.param(
            "mongodb",
            marks=[
                pytest.mark.skipif(
                    not HAVE_MONGODB,
                    reason="no mongodb",
                ),
                pytest.mark.mongodb,
            ],
        ),
    ],
)
def test_lazy_json(tmpdir, backend):
    with pushd(tmpdir):
        old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
        try:
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (backend,)
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                backend
            )

            f = "hi.json"
            sharded_path = get_sharded_path(f)
            assert not os.path.exists(f)
            lj = LazyJson(f)

            if backend == "file":
                assert os.path.exists(lj.file_name)
                assert os.path.exists(sharded_path)
                with open(sharded_path) as ff:
                    assert ff.read() == json.dumps({})
            else:
                assert not os.path.exists(sharded_path)
                assert not os.path.exists(lj.file_name)

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
            be = LAZY_JSON_BACKENDS[backend]()
            be.hdel("lazy_json", ["hi"])

            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                old_backend
            )
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
        assert lj.json_ref == {"__lazy_json__": lj.file_name}
        assert lj.sharded_path == get_sharded_path(f"{lj.hashmap}/{lj.node}.json")

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


def test_github_base_url() -> None:
    github_backend = GithubLazyJsonBackend()
    assert github_backend.base_url == settings().graph_github_backend_raw_base_url
    github_backend.base_url = "https://github.com/lorem/ipsum"
    assert github_backend.base_url == "https://github.com/lorem/ipsum" + "/"


@pytest.mark.parametrize(
    "name, key",
    [
        ("node_attrs", "flask"),
        ("node_attrs", "requests"),
        ("node_attrs", "boto3"),
        ("node_attrs", "setuptools"),
    ],
)
def test_github_online_hexists_success(
    name: str,
    key: str,
) -> None:
    # this performs a web request
    assert GithubLazyJsonBackend().hexists(name, key)


@pytest.mark.parametrize(
    "name, key",
    [
        ("node_attrs", "this-package-will-not-ever-exist-invalid"),
        ("invalid-name", "flask"),
    ],
)
def test_github_online_hexists_failure(name: str, key: str) -> None:
    # this performs a web request
    assert not GithubLazyJsonBackend().hexists(name, key)


@mock.patch("requests.head")
def test_github_hexists_unexpected_status_code(request_mock: MagicMock) -> None:
    request_mock.return_value.status_code = 500

    with pytest.raises(RuntimeError, match="Unexpected status code 500"):
        GithubLazyJsonBackend().hexists("name", "key")


@pytest.fixture
def reset_github_backend():
    # In the future, the program architecture should be changed such that backend instances are shared, instead of
    # instantiating each backend multiple times (whenever it is needed). Then, this can be moved into instance
    # variables that don't need to be reset.
    GithubLazyJsonBackend._write_warned = False
    GithubLazyJsonBackend._n_requests = 0


def test_github_hdel(caplog, reset_github_backend) -> None:
    caplog.set_level(logging.DEBUG)
    backend = GithubLazyJsonBackend()
    backend.hdel("name", ["key1", "key2"])

    assert "Write operations to the GitHub online backend are ignored." in caplog.text

    backend.hdel("name2", ["key3"])

    # warning should only be once in log
    assert (
        caplog.text.count("Write operations to the GitHub online backend are ignored")
        == 1
    )


def test_github_hmset(caplog, reset_github_backend) -> None:
    caplog.set_level(logging.DEBUG)
    backend = GithubLazyJsonBackend()
    backend.hmset("name", {"a": "b"})

    assert "Write operations to the GitHub online backend are ignored." in caplog.text

    backend.hmset("name2", {})

    # warning should only be once in log
    assert (
        caplog.text.count("Write operations to the GitHub online backend are ignored")
        == 1
    )


def test_github_hset(caplog, reset_github_backend) -> None:
    caplog.set_level(logging.DEBUG)
    backend = GithubLazyJsonBackend()
    backend.hset("name", "key", "value")

    assert "Write operations to the GitHub online backend are ignored." in caplog.text

    backend.hset("name", "key", "value2")

    # warning should only be once in log
    assert (
        caplog.text.count("Write operations to the GitHub online backend are ignored")
        == 1
    )


def test_github_write_mix(caplog, reset_github_backend) -> None:
    caplog.set_level(logging.DEBUG)
    backend = GithubLazyJsonBackend()

    backend.hset("name", "key", "value")
    backend.hdel("name", ["a", "b"])
    backend.hmset("name2", {"a": "d"})
    backend.hset("name", "key", "value")
    backend.hdel("name3", ["a", "b"])
    backend.hmset("name", {"a": "d"})

    # warning should only be once in log
    assert (
        caplog.text.count("Write operations to the GitHub online backend are ignored")
        == 1
    )


def test_github_hkeys() -> None:
    with pytest.raises(NotImplementedError):
        assert GithubLazyJsonBackend().hkeys("name") == []


def test_github_hgetall() -> None:
    with pytest.raises(NotImplementedError):
        GithubLazyJsonBackend().hgetall("name")


@mock.patch("requests.get")
def test_github_hget_success(
    mock_get: MagicMock,
) -> None:
    backend = GithubLazyJsonBackend()
    backend.base_url = "https://github.com/lorem/ipsum"
    mock_get.return_value.status_code = 200
    mock_get.return_value.text = "{'key': 'value'}"
    assert backend.hget("name", "key") == "{'key': 'value'}"
    mock_get.assert_called_once_with(
        "https://github.com/lorem/ipsum/name/4/4/0/9/d/key.json",
    )


@mock.patch("requests.get")
def test_github_offline_hget_not_found(
    mock_get: MagicMock,
) -> None:
    backend = GithubLazyJsonBackend()
    backend.base_url = "https://github.com/lorem/ipsum"
    mock_get.return_value.status_code = 404
    with pytest.raises(KeyError):
        backend.hget("name", "key")
    mock_get.assert_called_once_with(
        "https://github.com/lorem/ipsum/name/4/4/0/9/d/key.json",
    )


@pytest.mark.parametrize(
    "name, key",
    [
        ("node_attrs", "this-package-will-not-ever-exist-invalid"),
        ("invalid-name", "flask"),
    ],
)
def test_github_online_hget_not_found(name: str, key: str):
    with pytest.raises(KeyError):
        GithubLazyJsonBackend().hget(name, key)


def test_lazy_json_eq():
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(str(tmpdir)),
        lazy_json_override_backends(["github"]),
    ):
        ngmix = LazyJson("node_attrs/ngmix.json")
        touch_all_lazy_json_refs(ngmix)
        ngmix2 = LazyJson("node_attrs/ngmix.json")
        touch_all_lazy_json_refs(ngmix2)

        fitsio = LazyJson("node_attrs/fitsio.json")
        touch_all_lazy_json_refs(ngmix2)

        assert ngmix == ngmix2
        assert fitsio != ngmix2
        assert ngmix2 == ngmix
        assert ngmix2 != fitsio

        assert ngmix.data == ngmix2
        assert ngmix2 == ngmix.data

        assert ngmix.data == ngmix2.data
        assert fitsio.data != ngmix2.data
        assert ngmix2.data == ngmix.data
        assert ngmix2.data != fitsio.data

        with ngmix["pr_info"] as pri:
            pri.clear()
        assert ngmix.data != ngmix2.data
        assert ngmix2.data != ngmix.data
        assert ngmix != ngmix2
        assert ngmix2 != ngmix

        del ngmix.data["pr_info"]
        assert ngmix.data != ngmix2.data
        assert ngmix2.data != ngmix.data
        assert ngmix != ngmix2
        assert ngmix2 != ngmix


@pytest.mark.skipif(
    not conda_forge_tick.global_sensitive_env.classified_info.get("BOT_TOKEN", None),
    reason="No token for live tests.",
)
def test_lazy_json_backends_github_api():
    uid = uuid.uuid4().hex
    node = f"test_file_h{uid}"
    fname = node + ".json"

    # to make the i/o nice for -s
    print("", flush=True)

    def _sleep():
        print("sleeping for 5 seconds to allow github to update", flush=True)
        time.sleep(5)

    try:
        with lazy_json_override_backends(["github_api"], use_file_cache=False):
            backend = LAZY_JSON_BACKENDS[get_lazy_json_primary_backend()]()

            assert not backend.hexists("lazy_json", node)
            lzj = LazyJson(fname)
            assert not backend.hexists("lazy_json", node)
            with lzj:
                lzj["uid"] = uid
            _sleep()
            assert backend.hexists("lazy_json", node)
            assert json.loads(backend.hget("lazy_json", node))["uid"] == lzj.data["uid"]

            with lzj:
                lzj["uid"] = "new_uid"
            _sleep()
            assert json.loads(backend.hget("lazy_json", node))["uid"] == lzj.data["uid"]

            backend.hdel("lazy_json", [node])
            _sleep()
            assert not backend.hexists("lazy_json", node)
    finally:
        gh = github_client()
        repo = gh.get_repo("regro/cf-graph-countyfair")
        message = f"remove files {fname} from testing"
        for tr in range(10):
            try:
                contents = repo.get_contents(fname)
                repo.delete_file(fname, message, contents.sha)
                break
            except Exception:
                pass


@pytest.mark.skipif(
    not conda_forge_tick.global_sensitive_env.classified_info.get("BOT_TOKEN", None),
    reason="No token for live tests.",
)
def test_lazy_json_backends_github_api_nopush():
    uid = uuid.uuid4().hex
    node = f"test_file_h{uid}"
    fname = node + ".json"

    # to make the i/o nice for -s
    print("", flush=True)

    def _sleep():
        print("sleeping for 5 seconds to allow github to update", flush=True)
        time.sleep(5)

    try:
        with lazy_json_override_backends(["github_api"], use_file_cache=False):
            gh = github_client()
            repo = gh.get_repo("regro/cf-graph-countyfair")

            lzj = LazyJson(fname)
            with lzj:
                lzj["uid"] = uid
            _sleep()

            cnt = repo.get_contents(fname)
            curr_data = base64.b64decode(cnt.content.encode("utf-8")).decode("utf-8")
            assert json.loads(curr_data)["uid"] == lzj.data["uid"]

            with lzj:
                pass
            _sleep()
            cnt_again = repo.get_contents(fname)
            assert cnt.sha == cnt_again.sha
            curr_data = base64.b64decode(cnt_again.content.encode("utf-8")).decode(
                "utf-8"
            )
            assert json.loads(curr_data)["uid"] == lzj.data["uid"]

            with lzj:
                lzj["uid"] = "new_uid"
            _sleep()
            curr_data = base64.b64decode(
                repo.get_contents(fname).content.encode("utf-8")
            ).decode("utf-8")
            assert json.loads(curr_data)["uid"] == lzj.data["uid"]

    finally:
        message = f"remove files {fname} from testing"
        fnames = [fname]
        for _fname in fnames:
            for tr in range(10):
                try:
                    contents = repo.get_contents(_fname)
                    repo.delete_file(_fname, message, contents.sha)
                    break
                except Exception as e:
                    if tr == 9:
                        raise e
                    else:
                        pass


@pytest.mark.parametrize("hashmap", ["lazy_json", "pr_info"])
@pytest.mark.parametrize(
    "backend",
    [
        "file-read-only",
    ],
)
def test_lazy_json_backends_ops_readonly(backend, hashmap, tmpdir):
    be = LAZY_JSON_BACKENDS[backend]()
    rwbe = LAZY_JSON_BACKENDS["file"]()
    key = "blah"
    value = dumps({"a": 1, "b": 2})
    key_again = "blahblah"
    value_again = dumps({"a": 1, "b": 2, "c": 3})

    with pushd(tmpdir):
        try:
            assert not be.hexists(hashmap, key)
            assert be.hkeys(hashmap) == []

            with pytest.raises(RuntimeError):
                be.hset(hashmap, key, value)
            rwbe.hset(hashmap, key, value)
            assert be.hget(hashmap, key) == value
            assert be.hexists(hashmap, key)
            assert be.hkeys(hashmap) == [key]

            assert not be.hsetnx(hashmap, key, dumps({}))
            assert be.hget(hashmap, key) == value

            with pytest.raises(RuntimeError):
                be.hdel(hashmap, [key])
            rwbe.hdel(hashmap, [key])
            assert not be.hexists(hashmap, key)
            assert be.hkeys(hashmap) == []

            with pytest.raises(RuntimeError):
                assert be.hsetnx(hashmap, key, value)
            assert rwbe.hsetnx(hashmap, key, value)
            assert be.hget(hashmap, key) == value
            assert be.hexists(hashmap, key)
            assert be.hkeys(hashmap) == [key]

            with pytest.raises(RuntimeError):
                be.hdel(hashmap, [key])
            rwbe.hdel(hashmap, [key])
            assert not be.hexists(hashmap, key)
            assert be.hkeys(hashmap) == []

            mapping = {key: value, key_again: value_again}
            with pytest.raises(RuntimeError):
                be.hmset(hashmap, mapping)
            rwbe.hmset(hashmap, mapping)
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
            rwbe.hdel(hashmap, [key, key_again])


@pytest.mark.parametrize(
    "backend",
    [
        "file-read-only",
    ],
)
def test_lazy_json_read_only(tmpdir, backend):
    with pushd(tmpdir):
        old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
        try:
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (backend,)
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                backend
            )

            f = "hi.json"
            sharded_path = get_sharded_path(f)
            assert not os.path.exists(f)
            lj = LazyJson(f)
            assert not os.path.exists(sharded_path)
            assert not os.path.exists(lj.file_name)

            with lazy_json_override_backends(["file"]):
                with lj:
                    pass
                assert os.path.exists(lj.file_name)
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

            with pytest.raises(RuntimeError):
                with lj as attrs:
                    attrs["hi"] = "world"
            assert lj == {"hi": "world"}
            assert os.path.exists(sharded_path)
            with open(sharded_path) as ff:
                assert ff.read() == dumps({})

            with lazy_json_override_backends(["file"]):
                with lj as attrs:
                    attrs["hi"] = "world"
            assert lj["hi"] == "world"
            assert os.path.exists(sharded_path)
            with open(sharded_path) as ff:
                assert ff.read() == dumps({"hi": "world"})

            with pytest.raises(RuntimeError):
                with lj as attrs:
                    attrs.update({"hi": "globe"})
                    attrs.setdefault("lst", []).append("universe")
            assert lj == {"hi": "globe", "lst": ["universe"]}
            assert os.path.exists(sharded_path)
            with open(sharded_path) as ff:
                assert ff.read() == dumps({"hi": "world"})

            with pytest.raises(RuntimeError):
                with lj as attrs:
                    del attrs["hi"]
            assert lj == {"lst": ["universe"]}
            assert os.path.exists(sharded_path)
            with open(sharded_path) as ff:
                assert ff.read() == dumps({"hi": "world"})

            with pytest.raises(RuntimeError):
                with lj as attrs:
                    attrs.pop("lst")
            assert lj == {}
            assert os.path.exists(sharded_path)
            with open(sharded_path) as ff:
                assert ff.read() == dumps({"hi": "world"})

            assert len(lj) == 0

            with lazy_json_override_backends(["file"]):
                with lj as attrs:
                    attrs["hi"] = "world"
            assert lj["hi"] == "world"
            assert os.path.exists(sharded_path)
            with open(sharded_path) as ff:
                assert ff.read() == dumps({"hi": "world"})
            with pytest.raises(RuntimeError):
                with lj as attrs:
                    attrs.clear()
            assert lj == {}
            assert os.path.exists(sharded_path)
            with open(sharded_path) as ff:
                assert ff.read() == dumps({"hi": "world"})
        finally:
            be = LAZY_JSON_BACKENDS["file"]()
            be.hdel("lazy_json", ["hi"])

            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                old_backend
            )
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                old_backend[0]
            )
