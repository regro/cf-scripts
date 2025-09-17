import copy

import networkx as nx

from conda_forge_tick.git_utils import github_client
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    lazy_json_override_backends,
)
from conda_forge_tick.make_graph import (
    _add_run_exports_per_node,
    try_load_feedstock,
)


def _update_feedstocks(name: str) -> None:
    gh = github_client()
    repo = gh.get_repo(f"conda-forge/{name}-feedstock")

    with lazy_json_override_backends(["github_api"], use_file_cache=False):
        with LazyJson("all_feedstocks.json") as feedstocks:
            if repo.archived:
                if name in feedstocks["active"]:
                    feedstocks["active"].remove(name)
                if name not in feedstocks["archived"]:
                    feedstocks["archived"].append(name)
            elif not repo.archived:
                if name in feedstocks["archived"]:
                    feedstocks["archived"].remove(name)
                if name not in feedstocks["active"]:
                    feedstocks["active"].append(name)

            return copy.deepcopy(feedstocks.data)


def _react_to_push(name: str, dry_run: bool = False) -> None:
    fname = f"node_attrs/{name}.json"

    # first update the feedstocks
    all_feedstocks = _update_feedstocks(name)

    with lazy_json_override_backends(["github_api"], use_file_cache=False):
        with LazyJson("graph.json") as graph_json:
            gx = nx.node_link_graph(copy.deepcopy(graph_json.data), edges="links")

        with LazyJson(fname) as attrs:
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
                if name in all_feedstocks["archived"]:
                    attrs["archived"] = True
            else:
                print("dry run - checking archived", flush=True)


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
