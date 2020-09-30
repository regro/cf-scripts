import os
import json
import pickle

import pytest

from conda_forge_tick.utils import LazyJson, get_requirements, dumps, extract_canonical_imports


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


xonsh_files = json.load(open(f'{os.path.dirname(__file__)}/file_listings/xonsh.json'))
setuptools_files = json.load(open(f'{os.path.dirname(__file__)}/file_listings/setuptools.json'))
google_cloud_sotrage_files = json.load(open(f'{os.path.dirname(__file__)}/file_listings/google_cloud_storage.json'))


@pytest.mark.parametrize('files, expected_imports', [
    (xonsh_files, {'xonsh'}),
    (setuptools_files, {'_distutils_hack', 'setuptools', 'pkg_resources'}),
    (google_cloud_sotrage_files, {'google.cloud.storage'})
])
def test_extract_canonical_imports(files, expected_imports):
    assert extract_canonical_imports(files) == expected_imports
