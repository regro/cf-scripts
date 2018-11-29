import os
import json
import pickle

from conda_forge_tick.utils import (LazyJson, get_requirements)


def test_lazy_json(tmpdir):
    f = os.path.join(tmpdir, "hi.json")
    assert not os.path.exists(f)
    lj = LazyJson(f)
    assert os.path.exists(lj.file_name)
    with open(f, "r") as ff:
        assert ff.read() == json.dumps({}, indent=4)
    lj["hi"] = "world"
    assert lj["hi"] == "world"
    assert os.path.exists(lj.file_name)
    with open(f, "r") as ff:
        assert ff.read() == json.dumps({"hi": "world"}, indent=4)
    lj.update({"hi": "globe"})
    with open(f, "r") as ff:
        assert ff.read() == json.dumps({"hi": "globe"}, indent=4)
    p = pickle.dumps(lj)
    lj2 = pickle.loads(p)
    assert not getattr(lj2, "data", None)
    assert lj2["hi"] == "globe"


def test_get_requirements():
    meta_yaml = {
        "requirements": {
            "build": ["1", "2"],
            "host": ["2", "3"],
        },
        "outputs": [
            {"requirements": {"host": ["4"]},},
            {"requirements": {"run": ["5"]},},
        ],
    }
    assert get_requirements({}) == set()
    assert get_requirements(meta_yaml) == set(["1", "2", "3", "4", "5"])
    assert get_requirements(meta_yaml, outputs=False) == set(["1", "2", "3"])
    assert get_requirements(meta_yaml, host=False) == set(["1", "2", "5"])
