import pytest

from conda_forge_tick.update_sources import url_exists


@pytest.mark.parametrize(
    "url,exists",
    [
        ("https://github.com/beckermr/pizza-cutter/archive/0.2.2.tar.gz", True),
        ("https://github.com/beckermr/pizza-cutter/archive/0.2.3454794.tar.gz", False),
        (
            "http://ftp.openbsd.org/pub/OpenBSD/OpenSSH/portable/openssh-7.6p1.tar.gz",
            True,
        ),
        pytest.param(
            "https://eups.lsst.codes/stack/src/tags/w_2021_07.list",
            True,
            marks=pytest.mark.xfail(reason="expired HTTPS certificate"),
        ),
        pytest.param(
            "https://downloads.sourceforge.net/project/healpix/Healpix_3.31/Healpix_3.31_2016Aug26.tar.gz",  # noqa
            True,
            marks=pytest.mark.xfail(reason="sourceforge changed something"),
        ),
        (
            "https://downloads.sourceforge.net/project/healpix/Healpix_3.345/Healpix_3.345_2016Aug26.tar.gz",  # noqa
            False,
        ),
        (
            "http://spams-devel.gforge.inria.fr/hitcounter2.php?file/38351/spams-2.34832948372903465.tar.gz",  # noqa
            False,
        ),
        pytest.param(
            "http://spams-devel.gforge.inria.fr/hitcounter2.php?file=37237/spams-python-v2.6.1-svn2017-12-08.tar.gz",  # noqa
            True,
            marks=pytest.mark.xfail(reason="sourceforge changed something"),
        ),
        (
            "https://github.com/Kitware/CMake/releases/download/v3.19.4/cmake-3.19.4.tar.gz",  # noqa
            True,
        ),
        (
            "https://github.com/Kitware/CMake/releases/download/v3.19.4435784/cmake-3.19.4435784.tar.gz",  # noqa
            False,
        ),
        pytest.param(
            "ftp://ftp.info-zip.org/pub/infozip/src/zip30.tgz",
            True,
            marks=pytest.mark.xfail(reason="sometimes this fails"),
        ),
        (
            "ftp://ftp.info-zip.org/pub/infozip/src/zip33879130.tgz",
            False,
        ),
    ],
)
def test_url_exists(url, exists):
    # sourceforge seems slow enough to time out in our tests?
    if "sourceforge" in url:
        kwargs = dict(timeout=5)
    else:
        kwargs = {}
    assert url_exists(url, **kwargs) is exists
