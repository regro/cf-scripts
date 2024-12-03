import copy
import tempfile

import networkx as nx
import requests

from conda_forge_tick.git_utils import github_client
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    lazy_json_override_backends,
    push_lazy_json_via_gh_api,
)
from conda_forge_tick.make_graph import (
    _add_run_exports_per_node,
    _migrate_schema,
    try_load_feedstock,
)
from conda_forge_tick.os_utils import pushd


def _get_feedstocks():
    r = requests.get(
        "https://raw.githubusercontent.com/regro/cf-graph-countyfair/refs/heads/master/all_feedstocks.json"
    )
    r.raise_for_status()
    return r.json()


def _get_archived_feedstocks():
    return _get_feedstocks()["archived"]


def _update_feedstocks(name: str) -> None:
    feedstocks = copy.deepcopy(_get_feedstocks())

    gh = github_client()
    repo = gh.get_repo(f"conda-forge/{name}-feedstock")
    changed = False
    if repo.archived:
        if name in feedstocks["active"]:
            feedstocks["active"].remove(name)
            changed = True
        if name not in feedstocks["archived"]:
            feedstocks["archived"].append(name)
            changed = True
    elif not repo.archived:
        if name in feedstocks["archived"]:
            feedstocks["archived"].remove(name)
            changed = True
        if name not in feedstocks["active"]:
            feedstocks["active"].append(name)
            changed = True

    if changed:
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            pushd(str(tmpdir)),
            lazy_json_override_backends(["file"]),
        ):
            with LazyJson("all_feedstocks.json") as f:
                f.update(feedstocks)
            push_lazy_json_via_gh_api(f)


def _react_to_push(name: str, dry_run: bool = False) -> None:
    updated_node = False
    fname = f"node_attrs/{name}.json"

    # first update the feedstocks
    _update_feedstocks(name)

    # now pull down the data
    with lazy_json_override_backends(["github"], use_file_cache=False):
        try:
            attrs_data = copy.deepcopy(LazyJson(fname).data)
        except KeyError as e:
            if f"{name} not found in hashmap node_attrs" in str(e):
                attrs_data = {}
            else:
                raise e
        graph_data = copy.deepcopy(LazyJson("graph.json").data)
        gx = nx.node_link_graph(graph_data, edges="links")

    # now update the node
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(str(tmpdir)),
        lazy_json_override_backends(["file"]),
    ):
        attrs = LazyJson(fname)
        with attrs:
            attrs.update(attrs_data)

        with attrs:
            data_before = copy.deepcopy(attrs.data)

            if not dry_run:
                try_load_feedstock(name, attrs, mark_not_archived=True)
            else:
                print("dry run - loading feedstock", flush=True)

            if not dry_run:
                _add_run_exports_per_node(
                    attrs,
                    gx.graph["outputs_lut"],
                    gx.graph["strong_exports"],
                )
            else:
                print("dry run - adding run exports", flush=True)

            if not dry_run:
                _migrate_schema(name, attrs)
            else:
                print("dry run - migrating schema", flush=True)

            if not dry_run:
                archived_names = _get_archived_feedstocks()
                if name in archived_names:
                    attrs["archived"] = True
            else:
                print("dry run - checking archived", flush=True)

            if not dry_run and data_before != attrs.data:
                updated_node = True

        if not dry_run and updated_node:
            push_lazy_json_via_gh_api(attrs)
            print("pushed node update", flush=True)
        else:
            print("no changes to push", flush=True)


def react_to_push(uid: str, dry_run: bool = False) -> None:
    """React to a push event.

    Parameters
    ----------
    uid : str
        The unique identifier of the event. This is the name of the feedstock
        without `-feedstock`.
    dry_run : bool, optional
        If True, do not actually make any changes, by default False.
    """
    ntries = 10
    for nt in range(ntries):
        try:
            _react_to_push(uid, dry_run=dry_run)
            break
        except Exception as e:
            print(
                "failed to push node update - trying %d more times" % (ntries - nt - 1),
                flush=True,
            )
            if nt == ntries - 1:
                raise e
