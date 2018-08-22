import os
import json
import pickle

from conda_forge_tick.utils import LazyJson


def test_lazy_json(tmpdir):
    f = os.path.join(tmpdir, "hi.json")
    assert not os.path.exists(f)
    lj = LazyJson(f)
    assert os.path.exists(lj.file_name)
    with open(f, "r") as ff:
        assert ff.read() == json.dumps({})
    lj["hi"] = "world"
    assert lj["hi"] == "world"
    assert os.path.exists(lj.file_name)
    with open(f, "r") as ff:
        assert ff.read() == json.dumps({"hi": "world"})
    lj.update({"hi": "globe"})
    with open(f, "r") as ff:
        assert ff.read() == json.dumps({"hi": "globe"})
    p = pickle.dumps(lj)
    lj2 = pickle.loads(p)
    assert not getattr(lj2, "data", None)
    assert lj2["hi"] == "globe"
