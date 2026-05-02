import json
import subprocess

import networkx as nx
import pytest
from conftest import HAVE_CONTAINERS_AND_TEST_IMAGE, FakeLazyJson

from conda_forge_tick.lazy_json_backends import LazyJson
from conda_forge_tick.make_graph import (
    dump_graph,
    load_existing_graph,
    try_load_feedstock,
)
from conda_forge_tick.make_graph import main as make_graph_main
from conda_forge_tick.os_utils import pushd


@pytest.mark.parametrize("container_enabled", [HAVE_CONTAINERS_AND_TEST_IMAGE, False])
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


@pytest.mark.parametrize(
    "kwargs", [{"update_nodes_and_edges": True}, {"schema_migration_only": True}]
)
def test_make_graph_nowrite(tmp_path, kwargs):
    with pushd(str(tmp_path)):
        subprocess.run(["git", "init", "."], check=True, capture_output=True)

        (tmp_path / "all_feedstocks.json").write_text(
            json.dumps(
                {
                    "active": ["foo", "bar"],
                    "archived": ["baz"],
                }
            )
        )

        with LazyJson("node_attrs/foo.json") as attrs:
            attrs.update(
                dict(
                    feedstock_name="foo",
                    bad=False,
                    archived=False,
                    parsing_error=False,
                )
            )

        with LazyJson("node_attrs/baz.json") as attrs:
            attrs.update(
                dict(
                    feedstock_name="baz",
                    bad=False,
                    archived=True,
                    parsing_error=False,
                )
            )

        gx = nx.DiGraph()
        gx.add_node("foo", payload=LazyJson("node_attrs/foo.json"))
        gx.add_node("baz", payload=LazyJson("node_attrs/baz.json"))
        dump_graph(gx)

        make_graph_main(
            None,
            **kwargs,
        )

        fnames = sorted(list(tmp_path.glob("**/*.json")))
        assert not any(fname.name == "bar.json" for fname in fnames), sorted(
            fname.relative_to(tmp_path) for fname in fnames
        )

        # run again to ensure no empty files are made
        if "update_nodes_and_edges" in kwargs:
            make_graph_main(
                None,
                **kwargs,
            )

            fnames = sorted(list(tmp_path.glob("**/*.json")))
            assert not any(fname.name == "bar.json" for fname in fnames), sorted(
                fname.relative_to(tmp_path) for fname in fnames
            )

        gx = load_existing_graph()
        all_nodes = set(gx.nodes.keys())
        if "update_nodes_and_edges" in kwargs:
            assert "bar" in all_nodes, all_nodes

            # this load should not make a file
            fnames = sorted(list(tmp_path.glob("**/*.json")))
            assert not any(fname.name == "bar.json" for fname in fnames), sorted(
                fname.relative_to(tmp_path) for fname in fnames
            )
        else:
            assert "bar" not in all_nodes, all_nodes
