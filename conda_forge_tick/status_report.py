import csv
import os
import json
import subprocess
import copy
from collections import Counter

import networkx as nx
from graphviz import Source
import tempfile

from typing import Any, Dict, Set, Tuple

from conda_forge_tick.utils import frozen_to_json_friendly, load_graph
from conda_forge_tick.auto_tick import initialize_migrators
from conda_forge_tick.migrators import (
    Migrator,
    GraphMigrator,
    LicenseMigrator,
    Version,
    Replacement,
    MatplotlibBase,
)
from conda_forge_tick.path_lengths import cyclic_topological_sort
from conda_forge_tick.contexts import MigratorContext, FeedstockContext

from .git_utils import feedstock_url


GH_MERGE_STATE_STATUS = [
    "behind",
    "blocked",
    "clean",
    "dirty",
    "draft",
    "has_hooks",
    "unknown",
    "unstable",
]


def write_version_migrator_status(migrator, mctx):
    """write the status of the version migrator"""

    out = {
        "queued": [],
        "errored": [],
        "errors": {},
    }

    mmctx = MigratorContext(session=mctx, migrator=migrator)
    migrator.bind_to_ctx(mmctx)

    for node in mmctx.effective_graph.nodes:
        with mmctx.effective_graph.nodes[node]["payload"] as attrs:
            new_version = attrs.get("new_version", None)
            if new_version is None:
                continue
            attempts = attrs.get("new_version_attempts", {}).get(new_version, 0)
            if attempts == 0:
                out["queued"].append(node)
            else:
                out["errored"].append(node)
                out["errors"][node] = attrs.get("new_version_errors", {}).get(
                    new_version, "no error information available",
                )

    with open("./status/version_status.json", "w") as f:
        json.dump(out, f, sort_keys=True, indent=2)


def graph_migrator_status(
    migrator: Migrator, gx: nx.DiGraph,
) -> Tuple[dict, list, nx.DiGraph]:
    """Gets the migrator progress for a given migrator"""

    out: Dict[str, Set[str]] = {
        "done": set(),
        "in-pr": set(),
        "awaiting-pr": set(),
        "awaiting-parents": set(),
        "bot-error": set(),
    }

    gx2 = copy.deepcopy(getattr(migrator, "graph", gx))

    top_level = {node for node in gx2 if not list(gx2.predecessors(node))}
    build_sequence = list(cyclic_topological_sort(gx2, top_level))

    feedstock_metadata = dict()

    import graphviz
    from streamz.graph import _clean_text

    gv = graphviz.Digraph(graph_attr={"packmode": "array_3"})

    # pinning isn't actually in the migration
    if "conda-forge-pinning" in gx2.nodes():
        gx2.remove_node("conda-forge-pinning")

    for node, node_attrs in gx2.nodes.items():
        attrs = node_attrs["payload"]
        # remove archived from status
        if attrs.get("archived", False):
            continue
        node_metadata: Dict = {}
        feedstock_metadata[node] = node_metadata
        nuid = migrator.migrator_uid(attrs)
        all_pr_jsons = []
        for pr_json in attrs.get("PRed", []):
            all_pr_jsons.append(copy.deepcopy(pr_json))

        feedstock_ctx = FeedstockContext(
            package_name=node,
            feedstock_name=attrs.get("feedstock_name", node),
            attrs=attrs,
        )

        # hack around bug in migrator vs graph data for this one
        if isinstance(migrator, MatplotlibBase):
            if "name" in nuid:
                del nuid["name"]
            for i in range(len(all_pr_jsons)):
                if (
                    all_pr_jsons[i]
                    and "name" in all_pr_jsons[i]["data"]
                    and all_pr_jsons[i]["data"]["migrator_name"] == "MatplotlibBase"
                ):
                    del all_pr_jsons[i]["data"]["name"]

        for pr_json in all_pr_jsons:
            if pr_json and pr_json["data"] == frozen_to_json_friendly(nuid)["data"]:
                break
        else:
            pr_json = None

        # No PR was ever issued but the migration was performed.
        # This is only the case when the migration was done manually
        # before the bot could issue any PR.
        manually_done = pr_json is None and frozen_to_json_friendly(nuid)["data"] in (
            z["data"] for z in all_pr_jsons
        )

        buildable = not migrator.filter(attrs)
        fntc = "black"
        if manually_done:
            out["done"].add(node)
            fc = "#440154"
            fntc = "white"
        elif pr_json is None:
            if buildable:
                out["awaiting-pr"].add(node)
                fc = "#35b779"
            elif not isinstance(migrator, Replacement):
                out["awaiting-parents"].add(node)
                fc = "#fde725"
        elif "PR" not in pr_json:
            out["bot-error"].add(node)
            fc = "#000000"
            fntc = "white"
        elif pr_json["PR"]["state"] == "closed":
            out["done"].add(node)
            fc = "#440154"
            fntc = "white"
        else:
            out["in-pr"].add(node)
            fc = "#31688e"
            fntc = "white"
        if node not in out["done"]:
            gv.node(
                node,
                label=_clean_text(node),
                fillcolor=fc,
                style="filled",
                fontcolor=fntc,
                URL=(pr_json or {})
                .get("PR", {})
                .get(
                    "html_url",
                    feedstock_url(fctx=feedstock_ctx, protocol="https").strip(".git"),
                ),
            )

        # additional metadata for reporting
        node_metadata["num_descendants"] = len(nx.descendants(gx2, node))
        node_metadata["immediate_children"] = [
            k
            for k in sorted(gx2.successors(node))
            if not gx2[k].get("payload", {}).get("archived", False)
        ]
        if pr_json and "PR" in pr_json:
            # I needed to fake some PRs they don't have html_urls though
            node_metadata["pr_url"] = pr_json["PR"].get(
                "html_url",
                feedstock_url(fctx=feedstock_ctx, protocol="https").strip(".git"),
            )
            node_metadata["pr_status"] = pr_json["PR"].get('mergeable_state')

    out2: Dict = {}
    for k in out.keys():
        out2[k] = list(
            sorted(
                out[k],
                key=lambda x: build_sequence.index(x) if x in build_sequence else -1,
            ),
        )

    out2["_feedstock_status"] = feedstock_metadata
    for (e0, e1), edge_attrs in gx2.edges.items():
        if (
            e0 not in out["done"]
            and e1 not in out["done"]
            and not gx2.nodes[e0]["payload"].get("archived", False)
            and not gx2.nodes[e1]["payload"].get("archived", False)
        ):
            gv.edge(e0, e1)

    return out2, build_sequence, gv


def main(args: Any = None) -> None:
    mctx, *_, migrators = initialize_migrators()
    if not os.path.exists("./status"):
        os.mkdir("./status")
    total_status = {}

    for migrator in migrators:
        if isinstance(migrator, GraphMigrator) or isinstance(migrator, Replacement):
            if hasattr(migrator, "name"):
                assert isinstance(migrator.name, str)
                migrator_name = migrator.name.lower().replace(" ", "")
            else:
                migrator_name = migrator.__class__.__name__.lower()
            total_status[migrator_name] = f"{migrator.name} Migration Status"
            status, build_order, gv = graph_migrator_status(migrator, mctx.graph)
            with open(os.path.join(f"./status/{migrator_name}.json"), "w") as fp:
                json.dump(status, fp, indent=2)

            d = gv.pipe("dot")
            with tempfile.NamedTemporaryFile(suffix=".dot") as ntf:
                ntf.write(d)
                # make the graph a bit more compact
                d = Source(
                    subprocess.check_output(
                        ["unflatten", "-f", "-l", "5", "-c", "10", f"{ntf.name}"],
                    ).decode("utf-8"),
                ).pipe("svg")
            with open(os.path.join(f"./status/{migrator_name}.svg"), "wb") as fb:
                fb.write(d or gv.pipe("svg"))
        elif isinstance(migrator, Version):
            write_version_migrator_status(migrator, mctx)

    with open("./status/total_status.json", "w") as f:
        json.dump(total_status, f, sort_keys=True)

    lst = [
        k
        for k, v in mctx.graph.nodes.items()
        if len(
            [
                z
                for z in v.get("payload", {}).get("PRed", [])
                if z.get("PR", {}).get("state", "closed") == "open"
                and z.get("data", {}).get("migrator_name", "") == "Version"
            ],
        )
        >= Version.max_num_prs
    ]
    with open("./status/could_use_help.json", "w") as f:
        json.dump(
            sorted(
                lst,
                key=lambda z: (len(nx.descendants(mctx.graph, z)), lst),
                reverse=True,
            ),
            f,
            indent=2,
        )

    lm = LicenseMigrator()
    lst = [
        k for k, v in mctx.graph.nodes.items() if not lm.filter(v.get("payload", {}))
    ]
    with open("./status/unlicensed.json", "w") as f:
        json.dump(
            sorted(
                lst,
                key=lambda z: (len(nx.descendants(mctx.graph, z)), lst),
                reverse=True,
            ),
            f,
            indent=2,
        )
    open_prs = []
    gx = load_graph()
    for node, attrs in gx.nodes("payload"):
        for pr in attrs.get("PRed", []):
            if pr.get("PR", {}).get("state", "closed") != "closed":
                open_prs.append(pr["PR"])
    merge_state_count = Counter([o["mergeable_state"] for o in open_prs])
    with open("./status/pr_state.csv", "a") as f:
        writer = csv.writer(f)
        writer.writerow([merge_state_count[k] for k in GH_MERGE_STATE_STATUS])


if __name__ == "__main__":
    main()
