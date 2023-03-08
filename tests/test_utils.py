import os
import json
import pickle

from conda_forge_tick.utils import LazyJson, dumps, get_graph_data_redis_backend
import conda_forge_tick.utils


def test_lazy_json_file(tmpdir):
    old_backend = conda_forge_tick.utils.CF_TICK_GRAPH_DATA_BACKEND
    try:
        conda_forge_tick.utils.CF_TICK_GRAPH_DATA_BACKEND = "file"

        f = os.path.join(tmpdir, "hi.json")
        assert not os.path.exists(f)
        lj = LazyJson(f)
        assert os.path.exists(lj.file_name)
        with open(f) as ff:
            assert ff.read() == json.dumps({})
        lj["hi"] = "world"
        assert lj["hi"] == "world"
        assert os.path.exists(lj.file_name)
        with open(f) as ff:
            assert ff.read() == dumps({"hi": "world"})
        lj.update({"hi": "globe"})
        with open(f) as ff:
            assert ff.read() == dumps({"hi": "globe"})
        p = pickle.dumps(lj)
        lj2 = pickle.loads(p)
        assert not getattr(lj2, "_data", None)
        assert lj2["hi"] == "globe"

        with lj as attrs:
            attrs.setdefault("lst", []).append("universe")
        with open(f) as ff:
            assert ff.read() == dumps({"hi": "globe", "lst": ["universe"]})

        with lj as attrs:
            attrs.setdefault("lst", []).append("universe")
            with lj as attrs_again:
                attrs_again.setdefault("lst", []).append("universe")
                attrs.setdefault("lst", []).append("universe")
        with open(f) as ff:
            assert ff.read() == dumps({"hi": "globe", "lst": ["universe"] * 4})

        with lj as attrs:
            with lj as attrs_again:
                attrs_again.setdefault("lst2", []).append("universe")
                attrs.setdefault("lst2", []).append("universe")
        with open(f) as ff:
            assert ff.read() == dumps(
                {"hi": "globe", "lst": ["universe"] * 4, "lst2": ["universe"] * 2},
            )

        with lj as attrs:
            del attrs["lst"]
        with open(f) as ff:
            assert ff.read() == dumps(
                {"hi": "globe", "lst2": ["universe"] * 2},
            )

        with lj as attrs:
            attrs.pop("lst2")
        with open(f) as ff:
            assert ff.read() == dumps({"hi": "globe"})

        assert len(lj) == 1
        assert {k for k in lj} == {"hi"}

        lj.clear()
        with open(f) as ff:
            assert ff.read() == dumps({})
        assert len(lj) == 0
        assert not lj
    finally:
        conda_forge_tick.utils.CF_TICK_GRAPH_DATA_BACKEND = old_backend


def test_lazy_json_redis():
    old_backend = conda_forge_tick.utils.CF_TICK_GRAPH_DATA_BACKEND
    rd = None
    try:
        import redislite

        conda_forge_tick.utils.CF_TICK_GRAPH_DATA_BACKEND = "redislite"

        f = "hi.json"
        assert not os.path.exists("graph_data.db")
        lj = LazyJson(f)
        assert os.path.exists("graph_data.db.settings"), os.path.abspath(lj._dbname)

        rd = redislite.StrictRedis("graph_data.db")

        assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps({})

        lj["hi"] = "world"
        assert lj["hi"] == "world"
        assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps({"hi": "world"})

        lj.update({"hi": "globe"})
        assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps({"hi": "globe"})

        p = pickle.dumps(lj)
        lj2 = pickle.loads(p)
        assert not getattr(lj2, "_data", None)
        assert lj2["hi"] == "globe"
        assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps({"hi": "globe"})

        lj["hii"] = "world"
        assert lj["hii"] == "world"
        assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps(
            {"hii": "world", "hi": "globe"},
        )

        with lj as attrs:
            attrs.setdefault("lst", []).append("universe")

        assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps(
            {"hii": "world", "hi": "globe", "lst": ["universe"]},
        )

        with lj as attrs:
            attrs.setdefault("lst", []).append("universe")
            with lj as attrs_again:
                attrs_again.setdefault("lst", []).append("universe")
                attrs.setdefault("lst", []).append("universe")
        assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps(
            {"hii": "world", "hi": "globe", "lst": ["universe"] * 4},
        )

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

        with lj as attrs:
            del attrs["lst"]
        assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps(
            {"hii": "world", "hi": "globe", "lst2": ["universe"] * 2},
        )

        with lj as attrs:
            attrs.pop("lst2")
        assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps(
            {"hii": "world", "hi": "globe"},
        )

        assert len(lj) == 2
        assert {k for k in lj} == {"hi", "hii"}

        lj.clear()
        assert rd.hget("lazy_json", "hi").decode("utf-8") == dumps({})
        assert len(lj) == 0
        assert not lj

    finally:
        if rd is not None:
            rd.close()
        get_graph_data_redis_backend("graph_data.db").close()
        get_graph_data_redis_backend("graph_data.db").shutdown()
        get_graph_data_redis_backend.cache_clear()
        for fname in ["graph_data.db.settings", "graph_data.db"]:
            try:
                os.remove(fname)
            except Exception:
                pass
        conda_forge_tick.utils.CF_TICK_GRAPH_DATA_BACKEND = old_backend
