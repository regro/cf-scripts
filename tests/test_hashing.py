import pytest

from conda_forge_tick.hashing import _hash_url, hash_url


def test_hashing_smoke():
    url = "https://github.com/LSSTDESC/CLMM/archive/0.1.0.tar.gz"
    hsh = hash_url(url)
    assert hsh == "902cd1b15783a770a23b0950287f42e798f3b8aadb5bbf07b864ca37499a29e9"


def test_hashing_progress():
    url = "https://github.com/LSSTDESC/CLMM/archive/0.1.0.tar.gz"
    hsh = hash_url(url, progress=True)
    assert hsh == "902cd1b15783a770a23b0950287f42e798f3b8aadb5bbf07b864ca37499a29e9"


def test_hashing_timeout():
    url = "https://github.com/LSSTDESC/CLMM/archive/0.1.0.tar.gz"
    hsh = hash_url(url, timeout=0)
    assert hsh is None


def test_hashing_timeout_noprocess():
    url = "https://github.com/LSSTDESC/CLMM/archive/0.1.0.tar.gz"
    hsh = _hash_url(url, "sha256", timeout=0)
    assert hsh is None


def test_hashing_timeout_long():
    url = "http://gmsh.info/src/gmsh-4.5.3-source.tgz"
    hsh = hash_url(url, timeout=1)
    assert hsh is None


def test_hashing_timeout_long_noprocess():
    url = "http://gmsh.info/src/gmsh-4.5.3-source.tgz"
    hsh = _hash_url(url, "sha256", timeout=1)
    assert hsh is None


def test_hashing_timeout_notexist():
    url = "http://gmsh.info/src/gmsh-4.5.3-source.t"
    hsh = hash_url(url, timeout=1)
    assert hsh is None


def test_hashing_badtype():
    url = "https://github.com/LSSTDESC/CLMM/archive/0.1.0.tar.gz"
    with pytest.raises(AttributeError):
        hash_url(url, timeout=100, hash_type="blah")
