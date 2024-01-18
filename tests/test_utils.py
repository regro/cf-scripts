from conda_forge_tick.utils import get_keys_default


def test_get_keys_default():
    attrs = {
        "conda-forge.yml": {
            "bot": {
                "version_updates": {
                    "sources": ["pypi"],
                },
            },
        },
    }
    assert get_keys_default(
        attrs,
        ["conda-forge.yml", "bot", "version_updates", "sources"],
        {},
        None,
    ) == ["pypi"]
