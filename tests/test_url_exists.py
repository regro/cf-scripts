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
        ("https://eups.lsst.codes/stack/src/tags/w_2021_07.list", True),
        (
            "https://downloads.sourceforge.net/project/healpix/Healpix_3.31/Healpix_3.31_2016Aug26.tar.gz",  # noqa
            True,
        ),
        (
            "https://downloads.sourceforge.net/project/healpix/Healpix_3.345/Healpix_3.345_2016Aug26.tar.gz",  # noqa
            False,
        ),
        (
            "http://spams-devel.gforge.inria.fr/hitcounter2.php?file/38351/spams-2.6.2.5.tar.gz",  # noqa
            True,
        ),
        (
            "https://github.com/Kitware/CMake/releases/download/v3.19.4/cmake-3.19.4.tar.gz",  # noqa
            True,
        ),
        (
            "https://github.com/Kitware/CMake/releases/download/v3.19.4435784/cmake-3.19.4435784.tar.gz",  # noqa
            False,
        ),
    ],
)
def test_url_exists(url, exists):
    assert url_exists(url) is exists
