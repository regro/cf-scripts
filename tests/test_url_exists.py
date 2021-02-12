import pytest

from conda_forge_tick.update_sources import url_exists


@pytest.mark.parametrize("url,exists", [
    ("https://github.com/beckermr/pizza-cutter/archive/0.2.2.tar.gz", True)
    ("https://github.com/beckermr/pizza-cutter/archive/0.2.3454794.tar.gz", False),
    ("http://ftp.openbsd.org/pub/OpenBSD/OpenSSH/portable/openssh-7.6p1.tar.gz", True),
    ("https://eups.lsst.codes/stack/src/tags/w_2021_07.list", True),
])
def test_url_exists(url, exists):
    assert url_exists(url) is exists
