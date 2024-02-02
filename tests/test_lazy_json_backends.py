import hashlib
import json
import os
import pickle
from unittest import mock
from unittest.mock import MagicMock

import pytest

import conda_forge_tick.utils
from conda_forge_tick.backend_settings import GITHUB_GRAPH_BACKEND_BASE_URL
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
)
from conda_forge_tick.os_utils import pushd


@pytest.mark.skipif("MONGODB_CONNECTION_STRING" not in os.environ, reason="no mongodb")
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
        finally:
            be = LAZY_JSON_BACKENDS["mongodb"]()
            be.hdel("lazy_json", ["blah"])

            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                old_backend
            )
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                old_backend[0]
            )


@pytest.mark.skipif("MONGODB_CONNECTION_STRING" not in os.environ, reason="no mongodb")
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
@pytest.mark.parametrize(
    "backend",
    [
        "file",
        pytest.param(
            "mongodb",
            marks=pytest.mark.skipif(
                "MONGODB_CONNECTION_STRING" not in os.environ,
                reason="no mongodb",
            ),
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
            marks=pytest.mark.skipif(
                "MONGODB_CONNECTION_STRING" not in os.environ,
                reason="no mongodb",
            ),
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
            marks=pytest.mark.skipif(
                "MONGODB_CONNECTION_STRING" not in os.environ,
                reason="no mongodb",
            ),
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


class TestGithubLazyJsonBackend:
    base_url = "https://github.com/lorem/ipsum/raw/master"

    @pytest.fixture
    def backend(self) -> GithubLazyJsonBackend:
        github_backend = GithubLazyJsonBackend()
        github_backend.base_url = self.base_url
        return github_backend

    def test_base_url(self) -> None:
        github_backend = GithubLazyJsonBackend()
        assert github_backend.base_url == GITHUB_GRAPH_BACKEND_BASE_URL + "/"
        github_backend.base_url = self.base_url
        assert github_backend.base_url == self.base_url + "/"

    @mock.patch("requests.head")
    def test_hexists_success(
        self,
        mock_head: MagicMock,
        backend: GithubLazyJsonBackend,
    ) -> None:
        mock_head.return_value.status_code = 200
        assert backend.hexists("name", "key")
        mock_head.assert_called_once_with(
            f"{TestGithubLazyJsonBackend.base_url}/name/key.json",
        )

    @mock.patch("requests.head")
    def test_hexists_failure(
        self,
        mock_head: MagicMock,
        backend: GithubLazyJsonBackend,
    ) -> None:
        mock_head.return_value.status_code = 404
        assert not backend.hexists("name", "key")
        mock_head.assert_called_once_with(
            f"{TestGithubLazyJsonBackend.base_url}/name/key.json",
        )

    def test_hkeys(self, backend: GithubLazyJsonBackend) -> None:
        assert backend.hkeys("name") == []

    def test_hgetall(self, backend: GithubLazyJsonBackend) -> None:
        assert backend.hgetall("name") == {}

    @mock.patch("requests.get")
    def test_hget_success(
        self,
        mock_get: MagicMock,
        backend: GithubLazyJsonBackend,
    ) -> None:
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = "{'key': 'value'}"
        assert backend.hget("name", "key") == "{'key': 'value'}"
        mock_get.assert_called_once_with(
            f"{TestGithubLazyJsonBackend.base_url}/name/4/4/0/9/d/key.json",
        )

    @mock.patch("requests.get")
    def test_hget_not_found(
        self,
        mock_get: MagicMock,
        backend: GithubLazyJsonBackend,
    ) -> None:
        mock_get.return_value.status_code = 404
        with pytest.raises(KeyError):
            backend.hget("name", "key")
        mock_get.assert_called_once_with(
            f"{TestGithubLazyJsonBackend.base_url}/name/4/4/0/9/d/key.json",
        )
