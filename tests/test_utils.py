import os
import json
import pickle
import tempfile

from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    dumps,
    get_graph_data_redis_backend,
    get_sharded_path,
)
from conda_forge_tick.utils import pushd
import conda_forge_tick.utils

import pytest


def test_lazy_json_file(tmpdir):
    old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
    try:
        conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = ("file",)

        f = os.path.join(tmpdir, "hi.json")
        assert not os.path.exists(f)
        lj = LazyJson(f)
        assert not os.path.exists(lj.file_name)
        assert os.path.exists(lj.sharded_path)
        with open(lj.sharded_path) as ff:
            assert ff.read() == json.dumps({})

        with pytest.raises(AssertionError):
            lj.update({"hi": "globe"})
        with open(lj.sharded_path) as ff:
            assert ff.read() == dumps({})
        p = pickle.dumps(lj)
        lj2 = pickle.loads(p)
        assert not getattr(lj2, "_data", None)

        with lj as attrs:
            attrs["hi"] = "world"
        assert lj["hi"] == "world"
        assert os.path.exists(lj.sharded_path)
        with open(lj.sharded_path) as ff:
            assert ff.read() == dumps({"hi": "world"})

        with lj as attrs:
            attrs.update({"hi": "globe"})
            attrs.setdefault("lst", []).append("universe")
        with open(lj.sharded_path) as ff:
            assert ff.read() == dumps({"hi": "globe", "lst": ["universe"]})

        with lj as attrs:
            attrs.setdefault("lst", []).append("universe")
            with lj as attrs_again:
                attrs_again.setdefault("lst", []).append("universe")
                attrs.setdefault("lst", []).append("universe")
        with open(lj.sharded_path) as ff:
            assert ff.read() == dumps({"hi": "globe", "lst": ["universe"] * 4})

        with lj as attrs:
            with lj as attrs_again:
                attrs_again.setdefault("lst2", []).append("universe")
                attrs.setdefault("lst2", []).append("universe")
        with open(lj.sharded_path) as ff:
            assert ff.read() == dumps(
                {"hi": "globe", "lst": ["universe"] * 4, "lst2": ["universe"] * 2},
            )

        with lj as attrs:
            del attrs["lst"]
        with open(lj.sharded_path) as ff:
            assert ff.read() == dumps(
                {"hi": "globe", "lst2": ["universe"] * 2},
            )

        with lj as attrs:
            attrs.pop("lst2")
        with open(lj.sharded_path) as ff:
            assert ff.read() == dumps({"hi": "globe"})

        assert len(lj) == 1
        assert {k for k in lj} == {"hi"}

        with lj as attrs:
            attrs.clear()
        with open(lj.sharded_path) as ff:
            assert ff.read() == dumps({})
        assert len(lj) == 0
        assert not lj
    finally:
        conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = old_backend


def test_lazy_json_redis():
    old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
    rd = None
    with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
        try:
            import redislite

            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                "redislite",
            )

            f = "hi.json"
            assert not os.path.exists("cf-graph.db")
            lj = LazyJson(f)
            lj.data
            assert os.path.exists("cf-graph.db.settings")
            assert os.path.exists(lj.file_name)
            assert os.path.exists(lj.sharded_path)

            rd = redislite.StrictRedis("cf-graph.db")

            assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps({})

            with pytest.raises(AssertionError):
                lj.update({"hi": "globe"})

            with lj as attrs:
                attrs["hi"] = "world"
            assert lj["hi"] == "world"
            assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps({"hi": "world"})
            with open(lj.sharded_path) as fp:
                assert rd.hget("lazy_json", "hi").decode("utf-8") == fp.read()

            with lj as attrs:
                lj.update({"hi": "globe"})
            assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps({"hi": "globe"})
            with open(lj.sharded_path) as fp:
                assert rd.hget("lazy_json", "hi").decode("utf-8") == fp.read()

            p = pickle.dumps(lj)
            lj2 = pickle.loads(p)
            assert not getattr(lj2, "_data", None)
            assert lj2["hi"] == "globe"
            assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps({"hi": "globe"})
            with open(lj.sharded_path) as fp:
                assert rd.hget("lazy_json", "hi").decode("utf-8") == fp.read()

            with lj as attrs:
                attrs["hii"] = "world"
            assert lj["hii"] == "world"
            assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps(
                {"hii": "world", "hi": "globe"},
            )
            with open(lj.sharded_path) as fp:
                assert rd.hget("lazy_json", "hi").decode("utf-8") == fp.read()

            with lj as attrs:
                attrs.setdefault("lst", []).append("universe")

            assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps(
                {"hii": "world", "hi": "globe", "lst": ["universe"]},
            )
            with open(lj.sharded_path) as fp:
                assert rd.hget("lazy_json", "hi").decode("utf-8") == fp.read()

            with lj as attrs:
                attrs.setdefault("lst", []).append("universe")
                with lj as attrs_again:
                    attrs_again.setdefault("lst", []).append("universe")
                    attrs.setdefault("lst", []).append("universe")
            assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps(
                {"hii": "world", "hi": "globe", "lst": ["universe"] * 4},
            )
            with open(lj.sharded_path) as fp:
                assert rd.hget("lazy_json", "hi").decode("utf-8") == fp.read()

            with lj as attrs:
                with lj as attrs_again:
                    attrs_again.setdefault("lst2", []).append("universe")
                    attrs.setdefault("lst2", []).append("universe")
            assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps(
                {
                    "hii": "world",
                    "hi": "globe",
                    "lst": ["universe"] * 4,
                    "lst2": ["universe"] * 2,
                },
            )
            with open(lj.sharded_path) as fp:
                assert rd.hget("lazy_json", "hi").decode("utf-8") == fp.read()

            with lj as attrs:
                del attrs["lst"]
            assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps(
                {"hii": "world", "hi": "globe", "lst2": ["universe"] * 2},
            )
            with open(lj.sharded_path) as fp:
                assert rd.hget("lazy_json", "hi").decode("utf-8") == fp.read()

            with lj as attrs:
                attrs.pop("lst2")
            assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps(
                {"hii": "world", "hi": "globe"},
            )
            with open(lj.sharded_path) as fp:
                assert rd.hget("lazy_json", "hi").decode("utf-8") == fp.read()

            assert len(lj) == 2
            assert {k for k in lj} == {"hi", "hii"}

            with lj as attrs:
                attrs.clear()
            assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps({})
            assert len(lj) == 0
            assert not lj

        finally:
            if rd is not None:
                rd.close()
                rd.shutdown()
            get_graph_data_redis_backend("cf-graph.db").close()
            get_graph_data_redis_backend("cf-graph.db").shutdown()
            get_graph_data_redis_backend.cache_clear()
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                old_backend
            )


def test_lazy_json(tmpdir):
    f = os.path.join(tmpdir, "hi.json")
    fpth = get_sharded_path(f)
    assert not os.path.exists(fpth)
    lj = LazyJson(f)
    assert not os.path.exists(lj.file_name)
    assert os.path.exists(lj.sharded_path)
    assert fpth == lj.sharded_path
    with open(fpth) as ff:
        assert ff.read() == json.dumps({})

    with pytest.raises(AssertionError):
        lj.update({"hi": "globe"})

    p = pickle.dumps(lj)
    lj2 = pickle.loads(p)
    assert not getattr(lj2, "_data", None)

    with lj as attrs:
        attrs.setdefault("lst", []).append("universe")
    assert os.path.exists(lj.sharded_path)
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

    assert lj["hi"] == "world"

    assert len(lj) == 1
    assert {k for k in lj} == {"hi"}

    with lj as attrs:
        attrs.clear()
    with open(fpth) as ff:
        assert ff.read() == dumps({})
