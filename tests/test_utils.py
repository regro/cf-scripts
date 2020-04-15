import os
import json
import pickle

import pytest

from conda_forge_tick.utils import LazyJson, get_requirements, dumps, mamba_cant_solve, extract_requirements


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
        assert ff.read() == dumps({"hi": "world"})
    lj.update({"hi": "globe"})
    with open(f, "r") as ff:
        assert ff.read() == dumps({"hi": "globe"})
    p = pickle.dumps(lj)
    lj2 = pickle.loads(p)
    assert not getattr(lj2, "data", None)
    assert lj2["hi"] == "globe"


def test_get_requirements():
    meta_yaml = {
        "requirements": {"build": ["1", "2"], "host": ["2", "3"]},
        "outputs": [
            {"requirements": {"host": ["4"]}},
            {"requirements": {"run": ["5"]}},
            {"requirements": ["6"]},
        ],
    }
    assert get_requirements({}) == set()
    assert get_requirements(meta_yaml) == {"1", "2", "3", "4", "5", "6"}
    assert get_requirements(meta_yaml, outputs=False) == {"1", "2", "3"}
    assert get_requirements(meta_yaml, host=False) == {"1", "2", "5", "6"}


def test_mamba_cant_solve():
    assert mamba_cant_solve(['root==6.20.2', 'krb5=1.17.1'], os_arch='linux-64')
    assert not mamba_cant_solve(['pykerberos=1.2.1', 'krb5=1.17.1'], os_arch='linux-64')


@pytest.mark.parametrize('input_meta, expected_req', [
    ({'requirements': ['a', 'b', 'c']},
     {'run': {'a', 'b', 'c'}}),
    ({'requirements': {'build': ['a'], 'host': ['b'], 'run': ['c']}, 'test': {'requirements': ['d']}},
     {'build': {'a'}, 'host': {'b'}, 'run': {'c'}, 'test': {'d'}}),
    ({'requirements': {'build': ['a'], 'host': ['b'], 'run': ['c']}, 'test': {'requirements': ['d']},
      'outputs': [{'requirements': {'run': ['e']}, 'test': {'requires': ['f']}}]},
     {'build': {'a'}, 'host': {'b'}, 'run': {'c', 'e'}, 'test': {'d', 'f'}})
])
def test_extract_requirements(input_meta, expected_req):
    assert extract_requirements(input_meta) == expected_req
