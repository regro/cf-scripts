import csv
import os
import rapidjson as json
import subprocess
import copy
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

import dateutil.parser
import datetime
import networkx as nx
from graphviz import Source
import tempfile

import tqdm
import yaml

from typing import Any, Dict, Set, Tuple

from conda_forge_tick.utils import frozen_to_json_friendly
from conda_forge_tick.auto_tick import initialize_migrators
from conda_forge_tick.migrators import (
    Migrator,
    GraphMigrator,
    LicenseMigrator,
    Version,
    Replacement,
    MatplotlibBase,
    ArchRebuild,
    OSXArm,
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
        attrs = mmctx.effective_graph.nodes[node]["payload"]
        new_version = attrs.get("new_version", None)
        if new_version is None:
            continue
        attempts = attrs.get("new_version_attempts", {}).get(new_version, 0)
        if attempts == 0:
            out["queued"].append(node)
        else:
            out["errored"].append(node)
            out["errors"][node] = attrs.get("new_version_errors", {}).get(
                new_version,
                "No error information available for version '%s'." % new_version,
            )

    with open("./status/version_status.json", "w") as f:
        json.dump(out, f, sort_keys=True, indent=2)


def graph_migrator_status(
    migrator: Migrator,
    gx: nx.DiGraph,
) -> Tuple[dict, list, nx.DiGraph]:
    """Gets the migrator progress for a given migrator"""

    if hasattr(migrator, "name"):
        assert isinstance(migrator.name, str)
        migrator_name = migrator.name.lower().replace(" ", "")
    else:
        migrator_name = migrator.__class__.__name__.lower()

    num_viz = 0

    out: Dict[str, Set[str]] = {
        "done": set(),
        "in-pr": set(),
        "awaiting-pr": set(),
        "not-solvable": set(),
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
        status_icon = ""
        if manually_done:
            out["done"].add(node)
            fc = "#440154"
            fntc = "white"
        elif pr_json is None:
            if buildable:
                if "not solvable" in (
                    attrs.get("pre_pr_migrator_status", {}).get(migrator_name, "")
                ):
                    out["not-solvable"].add(node)
                    fc = "#ff8c00"
                elif "bot error" in (
                    attrs.get("pre_pr_migrator_status", {}).get(migrator_name, "")
                ):
                    out["bot-error"].add(node)
                    fc = "#000000"
                    fntc = "white"
                else:
                    out["awaiting-pr"].add(node)
                    fc = "#35b779"
            elif not isinstance(migrator, Replacement):
                if "bot error" in (
                    attrs.get("pre_pr_migrator_status", {}).get(migrator_name, "")
                ):
                    out["bot-error"].add(node)
                    fc = "#000000"
                    fntc = "white"
                else:
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
            pr_status = pr_json["PR"]["mergeable_state"]
            if pr_status == "clean":
                status_icon = " ✓"
            else:
                status_icon = " ❎"
        if node not in out["done"]:
            num_viz += 1
            gv.node(
                node,
                label=_clean_text(node) + status_icon,
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
        if node in out["not-solvable"] or node in out["bot-error"]:
            node_metadata["pre_pr_migrator_status"] = attrs.get(
                "pre_pr_migrator_status",
                {},
            ).get(migrator_name, "")
        else:
            node_metadata["pre_pr_migrator_status"] = ""

        if pr_json and "PR" in pr_json:
            # I needed to fake some PRs they don't have html_urls though
            node_metadata["pr_url"] = pr_json["PR"].get(
                "html_url",
                feedstock_url(fctx=feedstock_ctx, protocol="https").strip(".git"),
            )
            node_metadata["pr_status"] = pr_json["PR"].get("mergeable_state")

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

    print("    len(gv):", num_viz, flush=True)
    out2["_num_viz"] = num_viz

    return out2, build_sequence, gv


def _collect_items_from_nodes(gx, func):
    futs = []
    with ThreadPoolExecutor(max_workers=20) as exec:
        for k in gx.nodes:
            futs.append(exec.submit(func, k))
    return [
        fut.result()
        for fut in tqdm.tqdm(as_completed(futs), total=len(futs))
        if fut.result() is not None
    ]


def _compute_recently_closed(total_status, old_closed_status, old_total_status):
    now = int(time.time())
    two_weeks = 14 * 24 * 60 * 60

    # grab any new stuff
    closed_status = {m: now for m in set(old_total_status) - set(total_status)}

    # grab anything rcent from previous stuff
    for m, nm in old_closed_status.items():
        tm = int(dateutil.parser.parse(nm.split(" closed at ", 1)[1]).timestamp())
        if m not in total_status and now - tm < two_weeks:
            closed_status[m] = tm

    # now make it pretty
    closed_status = {
        k: (
            k
            + " closed at "
            + datetime.datetime.fromtimestamp(v).isoformat().replace("T", " ")
            + " UTC"
        )
        for k, v in closed_status.items()
    }

    return closed_status


def main(args: Any = None) -> None:
    import requests

    r = requests.get(
        "https://raw.githubusercontent.com/conda-forge/"
        "conda-forge.github.io/master/img/anvil.svg",
    )

    # cache these for later
    if os.path.exists("status/closed_status.json"):
        with open("status/closed_status.json") as fp:
            old_closed_status = json.load(fp)
    else:
        old_closed_status = {}

    with open("status/total_status.json") as fp:
        old_total_status = json.load(fp)

    mctx, *_, migrators = initialize_migrators()
    if not os.path.exists("./status"):
        os.mkdir("./status")
    regular_status = {}
    longterm_status = {}

    print(" ", flush=True)

    for migrator in migrators:
        if hasattr(migrator, "name"):
            assert isinstance(migrator.name, str)
            migrator_name = migrator.name.lower().replace(" ", "")
        else:
            migrator_name = migrator.__class__.__name__.lower()

        print(
            "================================================================",
            flush=True,
        )
        print("name:", migrator_name, flush=True)

        if isinstance(migrator, GraphMigrator) or isinstance(migrator, Replacement):
            if isinstance(migrator, GraphMigrator):
                mgconf = yaml.safe_load(getattr(migrator, "yaml_contents", "{}")).get(
                    "__migrator",
                    {},
                )
                if (
                    mgconf.get("longterm", False)
                    or isinstance(migrator, ArchRebuild)
                    or isinstance(migrator, OSXArm)
                ):
                    longterm_status[migrator_name] = f"{migrator.name} Migration Status"
                else:
                    regular_status[migrator_name] = f"{migrator.name} Migration Status"
            else:
                regular_status[migrator_name] = f"{migrator.name} Migration Status"
            status, build_order, gv = graph_migrator_status(migrator, mctx.graph)
            num_viz = status.pop("_num_viz", 0)
            with open(os.path.join(f"./status/{migrator_name}.json"), "w") as fp:
                json.dump(status, fp, indent=2)

            if num_viz <= 500:
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
            else:
                with open(os.path.join(f"./status/{migrator_name}.svg"), "wb") as fb:
                    fb.write(r.content)

        elif isinstance(migrator, Version):
            write_version_migrator_status(migrator, mctx)

        print(" ", flush=True)

    print("writing data", flush=True)
    with open("./status/regular_status.json", "w") as f:
        json.dump(regular_status, f, sort_keys=True, indent=2)

    with open("./status/longterm_status.json", "w") as f:
        json.dump(longterm_status, f, sort_keys=True, indent=2)

    total_status = {}
    total_status.update(regular_status)
    total_status.update(longterm_status)
    with open("./status/total_status.json", "w") as f:
        json.dump(total_status, f, sort_keys=True, indent=2)

    closed_status = _compute_recently_closed(
        total_status,
        old_closed_status,
        old_total_status,
    )
    with open("./status/closed_status.json", "w") as f:
        json.dump(closed_status, f, sort_keys=True, indent=2)

    print("\ncomputing feedstock and PR stats", flush=True)

    def _get_needs_help(k):
        v = mctx.graph.nodes[k]
        if (
            len(
                [
                    z
                    for z in v.get("payload", {}).get("PRed", [])
                    if z.get("PR", {}).get("state", "closed") == "open"
                    and z.get("data", {}).get("migrator_name", "") == "Version"
                ],
            )
            >= Version.max_num_prs
        ):
            return k
        else:
            return None

    lst = _collect_items_from_nodes(mctx.graph, _get_needs_help)
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

    def _get_needs_license(k):
        v = mctx.graph.nodes[k]
        if not lm.filter(v.get("payload", {})):
            return k
        else:
            return None

    lst = _collect_items_from_nodes(mctx.graph, _get_needs_license)
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

    def _get_open_pr_states(k):
        attrs = mctx.graph.nodes[k]
        _open_prs = []
        for pr in attrs.get("PRed", []):
            if pr.get("PR", {}).get("state", "closed") != "closed":
                _open_prs.append(pr["PR"])

        return _open_prs

    open_prs = []
    for op in _collect_items_from_nodes(mctx.graph, _get_open_pr_states):
        open_prs.extend(op)
    merge_state_count = Counter([o["mergeable_state"] for o in open_prs])
    with open("./status/pr_state.csv", "a") as f:
        writer = csv.writer(f)
        writer.writerow([merge_state_count[k] for k in GH_MERGE_STATE_STATUS])


if __name__ == "__main__":
    main()
