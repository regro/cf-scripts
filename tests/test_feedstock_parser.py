from conda_forge_tick.feedstock_parser import _get_requirements


def test_get_requirements():
    meta_yaml = {
        "requirements": {"build": ["1", "2"], "host": ["2", "3"]},
        "outputs": [
            {"requirements": {"host": ["4"]}},
            {"requirements": {"run": ["5"]}},
            {"requirements": ["6"]},
        ],
    }
    assert _get_requirements({}) == set()
    assert _get_requirements(meta_yaml) == {"1", "2", "3", "4", "5", "6"}
    assert _get_requirements(meta_yaml, outputs=False) == {"1", "2", "3"}
    assert _get_requirements(meta_yaml, host=False) == {"1", "2", "5", "6"}
