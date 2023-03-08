import os
import json
import pickle

from conda_forge_tick.utils import LazyJson, dumps, get_sharded_path


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
    lj["hi"] = "world"
    assert lj["hi"] == "world"
    assert os.path.exists(lj.sharded_path)
    with open(fpth) as ff:
        assert ff.read() == dumps({"hi": "world"})
    lj.update({"hi": "globe"})
    with open(fpth) as ff:
        assert ff.read() == dumps({"hi": "globe"})
    p = pickle.dumps(lj)
    lj2 = pickle.loads(p)
    assert not getattr(lj2, "_data", None)
    assert lj2["hi"] == "globe"

    with lj as attrs:
        attrs.setdefault("lst", []).append("universe")
    with open(fpth) as ff:
        assert ff.read() == dumps({"hi": "globe", "lst": ["universe"]})

    with lj as attrs:
        attrs.setdefault("lst", []).append("universe")
        with lj as attrs_again:
            attrs_again.setdefault("lst", []).append("universe")
            attrs.setdefault("lst", []).append("universe")
    with open(fpth) as ff:
        assert ff.read() == dumps({"hi": "globe", "lst": ["universe"] * 4})

    with lj as attrs:
        with lj as attrs_again:
            attrs_again.setdefault("lst2", []).append("universe")
            attrs.setdefault("lst2", []).append("universe")
    with open(fpth) as ff:
        assert ff.read() == dumps(
            {"hi": "globe", "lst": ["universe"] * 4, "lst2": ["universe"] * 2},
        )

    with lj as attrs:
        del attrs["lst"]
    with open(fpth) as ff:
        assert ff.read() == dumps(
            {"hi": "globe", "lst2": ["universe"] * 2},
        )

    with lj as attrs:
        attrs.pop("lst2")
    with open(fpth) as ff:
        assert ff.read() == dumps({"hi": "globe"})

    assert len(lj) == 1
    assert {k for k in lj} == {"hi"}

    lj.clear()
    with open(fpth) as ff:
        assert ff.read() == dumps({})
