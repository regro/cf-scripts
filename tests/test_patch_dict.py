from conda_forge_tick.migrators.migration_yaml import _patch_dict


def test_patch_dict():
    cfg = {
        "a": {"b": 1, "c": {"d": 10}},
        "e": {"f": 5, "g": {"h": 18}},
        "gh": [4, 5, 4, 4, 4, 4],
    }

    _patch_dict(
        cfg,
        {"a.c.d": 15, "e.f": {"k": 19}, "gh": 10, "x.y.z": 13, "new": 23}
    )

    assert cfg["a"]["b"] == 1
    assert cfg["a"]["c"]["d"] == 15
    assert cfg["e"]["f"] == {"k": 19}
    assert cfg["e"]["g"]["h"] == 18
    assert cfg["gh"] == 10
    assert "x.y.z" not in cfg
    assert cfg["new"] == 23
