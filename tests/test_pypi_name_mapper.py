import pathlib

from conda_forge_tick.os_utils import pushd
from conda_forge_tick.pypi_name_mapping import (
    extract_pypi_information,
    imports_to_canonical_import,
)

test_graph_dir = str(pathlib.Path(__file__).parent / "test_pypi_name_mapping")


def test_directory():
    with pushd(test_graph_dir):
        res = extract_pypi_information()
        import pprint

        pprint.pprint(res)

        # Simple easy case
        assert {
            "pypi_name": "psutil",
            "conda_name": "psutil",
            "import_name": "psutil",
            "mapping_source": "regro-bot",
        } in res

        # zope.interface  is a namespaced package so we check that we don't parse the
        # import_name as zope
        assert {
            "pypi_name": "zope-interface",
            "conda_name": "zope.interface",
            "import_name": "zope.interface",
            "mapping_source": "regro-bot",
        } in res

        # graphviz uses a legacy url and has a mismatch in its name between cf and pypi
        assert {
            "pypi_name": "graphviz",
            "conda_name": "py-graphviz",
            "import_name": "graphviz",
            "mapping_source": "regro-bot",
        } in res


def test_canonical_import_detection():
    assert imports_to_canonical_import(["psutil"]) == "psutil"
    assert imports_to_canonical_import(["a", "a.b", "a.c", "a.e.f"]) == "a"

    assert imports_to_canonical_import(["a", "a.b", "a.b.c", "a.b.d"]) == "a.b"
    assert (
        imports_to_canonical_import(["a", "a.b", "a.b.c", "a.b.c.d", "a.b.c.e"])
        == "a.b.c"
    )

    assert imports_to_canonical_import(["zope", "zope.interface"]) == "zope.interface"
    assert (
        imports_to_canonical_import(["google", "google.cloud", "google.cloud.some_svc"])
        == "google.cloud.some_svc"
    )

    assert imports_to_canonical_import(["a", "b"]) == ""
    assert imports_to_canonical_import(["a.b.c", "a.b.d"]) == "a.b"
