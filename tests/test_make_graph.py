import pytest
from conftest import FakeLazyJson

from conda_forge_tick.lazy_json_backends import LazyJson
from conda_forge_tick.make_graph import try_load_feedstock


@pytest.mark.parametrize("container_enabled", [True, False])
@pytest.mark.parametrize("existing_archived", [True, False, None])
@pytest.mark.parametrize("mark_not_archived", [True, False])
def test_try_load_feedstock(
    request: pytest.FixtureRequest,
    mark_not_archived: bool,
    existing_archived: bool | None,
    container_enabled: bool,
):
    if container_enabled:
        request.getfixturevalue("use_containers")

    feedstock = "typst-test"  # archived

    fake_lazy_json = FakeLazyJson()  # empty dict

    with fake_lazy_json as loaded_lazy_json:
        if existing_archived is not None:
            loaded_lazy_json["archived"] = existing_archived
        # FakeLazyJson is not an instance of LazyJson
        # noinspection PyTypeChecker
        data = try_load_feedstock(feedstock, loaded_lazy_json, mark_not_archived).data  # type: ignore

    if mark_not_archived:
        assert data["archived"] is False
    elif existing_archived is None:
        assert "archived" not in data
    else:
        assert data["archived"] is existing_archived

    assert data["feedstock_name"] == feedstock
    assert data["parsing_error"] is False
    assert data["raw_meta_yaml"].startswith("{% set name")
    assert isinstance(data["conda-forge.yml"], dict)
    assert "linux_64" in data["platforms"]
    assert data["meta_yaml"]["about"]["license"] == "MIT"
    assert isinstance(data["linux_64_meta_yaml"], dict)
    assert isinstance(data["linux_64_requirements"], dict)
    assert isinstance(data["total_requirements"], dict)
    assert data["strong_exports"] is False
    assert data["outputs_names"] == {feedstock}
    assert isinstance(data["req"], set)
    assert data["name"] == feedstock
    assert data["version"].startswith("0.")
    assert data["url"].startswith("https://github.com/tingerrr/typst-test")
    assert data["hash_type"] == "sha256"
    assert isinstance(data["version_pr_info"], LazyJson)
