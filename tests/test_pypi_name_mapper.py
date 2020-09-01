import pathlib
from conda_forge_tick.pypi_name_mapping import extract_pypi_information


test_graph_dir = str(pathlib.Path(__file__).parent / "test_pypi_name_mapping")


def test_directory():
    res = extract_pypi_information(test_graph_dir)
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
        "pypi_name": "zope.interface",
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
