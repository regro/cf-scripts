import copy
import datetime
import glob
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Set, Tuple, cast

import dateutil.parser
import networkx as nx
import orjson
import requests
import tqdm
import yaml
from conda.models.version import VersionOrder
from graphviz import Source

from conda_forge_tick.contexts import FeedstockContext, MigratorSessionContext
from conda_forge_tick.lazy_json_backends import LazyJson, get_all_keys_for_hashmap
from conda_forge_tick.make_migrators import load_migrators
from conda_forge_tick.migrators import (
    ArchRebuild,
    GraphMigrator,
    MatplotlibBase,
    MigrationYaml,
    MigrationYamlCreator,
    Migrator,
    OSXArm,
    Replacement,
    Version,
    WinArm64,
)
from conda_forge_tick.os_utils import eval_cmd
from conda_forge_tick.path_lengths import cyclic_topological_sort
from conda_forge_tick.utils import (
    fold_log_lines,
    frozen_to_json_friendly,
    load_existing_graph,
    pr_can_be_archived,
)
from conda_forge_tick.version_filters import filter_version

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

# Cache for migrators by name, loaded on demand
_migrators_by_name_cache: Dict[str, Migrator] | None = None


def _get_migrators_by_name() -> Dict[str, Migrator]:
    """Get mapping of migrator report_name to migrator instance.

    Uses a module-level cache to avoid reloading migrators multiple times.
    """
    global _migrators_by_name_cache
    if _migrators_by_name_cache is None:
        migrators = load_migrators(skip_paused=False)
        _migrators_by_name_cache = {m.report_name: m for m in migrators}
    return _migrators_by_name_cache


def _sorted_set_json(obj: Any) -> Any:
    """If obj is a set, return sorted(obj). Else, raise TypeError.

    Used for custom object serialization.

    Raises
    ------
    TypeError
        If obj is not a set.
    """
    if isinstance(obj, Set):
        return sorted(obj)
    raise TypeError(repr(obj) + " is not JSON serializable")


def _ok_version(ver):
    return ver is not None and ver and isinstance(ver, str)


def write_version_migrator_status(migrator, mctx):
    """Write the status of the version migrator."""
    out: Dict[str, Dict[str, str]] = {
        "queued": {},  # name -> pending version
        "errors": {},  # name -> error
    }

    gx = mctx.graph
    version_nodes = get_all_keys_for_hashmap("versions")

    for node in version_nodes:
        version_data = LazyJson(f"versions/{node}.json").data
        with gx.nodes[f"{node}"]["payload"] as attrs:
            if attrs.get("archived", False):
                continue

            with attrs["version_pr_info"] as vpri:
                version_from_data = filter_version(
                    attrs,
                    version_data.get("new_version", False),
                )
                version_from_attrs = filter_version(
                    attrs,
                    vpri.get("new_version", False),
                )
                if _ok_version(version_from_data):
                    if _ok_version(version_from_attrs):
                        new_version: str | bool = max(
                            [version_from_data, version_from_attrs],
                            key=lambda x: VersionOrder(x.replace("-", ".")),  # type: ignore[union-attr]
                        )
                    else:
                        new_version = version_from_data
                else:
                    new_version = vpri.get("new_version", False)

                try:
                    if "new_version" in vpri:
                        old_vpri_version = vpri["new_version"]
                        had_vpri_version = True
                    else:
                        had_vpri_version = False

                    vpri["new_version"] = new_version

                    new_version_is_ok = _ok_version(
                        new_version
                    ) and not migrator.filter(attrs)
                finally:
                    if had_vpri_version:
                        vpri["new_version"] = old_vpri_version
                    else:
                        del vpri["new_version"]

                # run filter with new_version
                if new_version_is_ok:
                    attempts = vpri.get("new_version_attempts", {}).get(new_version, 0)
                    if attempts == 0:
                        out["queued"][node] = new_version  # type: ignore[assignment]
                    else:
                        out["errors"][node] = f"{attempts:.2f} attempts - " + vpri.get(
                            "new_version_errors",
                            {},
                        ).get(
                            new_version,
                            "No error information available for version '%s'."
                            % new_version,
                        )

    with open("./status/version_status.json", "wb") as f:
        old_out: dict[str, dict[str, str] | set[str]] = {}
        old_out.update(out)
        old_out["queued"] = set(out["queued"].keys())
        old_out["errored"] = set(out["errors"].keys())
        f.write(
            orjson.dumps(
                old_out,
                option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2,
                default=_sorted_set_json,
            )
        )

    with open("./status/version_status.v2.json", "wb") as f:
        f.write(
            orjson.dumps(
                out,
                option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2,
                default=_sorted_set_json,
            )
        )


def _get_waiting_migrators(migrator: Migrator, attrs: dict) -> list[str]:
    """Get list of migrators that this package is waiting for.

    Returns empty list if not waiting for any migrators.
    """
    if not isinstance(migrator, MigrationYaml):
        return []

    migrator_payload = migrator.loaded_yaml.get("__migrator", {})
    wait_for_migrators = migrator_payload.get("wait_for_migrators", [])

    if not wait_for_migrators:
        return []

    # Check if we're actually waiting (i.e., migrators not all closed)
    found_migrators = set()
    for migration in attrs.get("pr_info", {}).get("PRed", []):
        name = migration.get("data", {}).get("name", "")
        if not name or name not in wait_for_migrators:
            continue
        found_migrators.add(name)
        state = migration.get("PR", {}).get("state", "")
        if state != "closed":
            # Still waiting for this one
            return list(wait_for_migrators)

    # Check if any migrators are missing
    missing_migrators = set(wait_for_migrators) - found_migrators
    if missing_migrators:
        return list(wait_for_migrators)

    return []


def graph_migrator_status(
    migrator: Migrator,
    gx: nx.DiGraph,
) -> Tuple[dict, list, nx.DiGraph]:
    """Get the migrator progress for a given migrator."""
    migrator_name = migrator.report_name

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
        for pr_json in attrs.get("pr_info", {}).get("PRed", []):
            all_pr_jsons.append(copy.deepcopy(pr_json))

        feedstock_ctx = FeedstockContext(
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

        if pr_json is not None and "PR" in pr_json:
            pr_is_archiveable = pr_can_be_archived(pr_json["PR"])
        else:
            pr_is_archiveable = False

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
                    attrs.get("pr_info", {})
                    .get("pre_pr_migrator_status", {})
                    .get(migrator_name, "")
                ):
                    out["not-solvable"].add(node)
                    fc = "#ff8c00"
                elif "bot error" in (
                    attrs.get("pr_info", {})
                    .get("pre_pr_migrator_status", {})
                    .get(migrator_name, "")
                ) or attrs.get("parsing_error", ""):
                    out["bot-error"].add(node)
                    fc = "#000000"
                    fntc = "white"
                else:
                    out["awaiting-pr"].add(node)
                    fc = "#35b779"
            else:
                if "bot error" in (
                    attrs.get("pr_info", {})
                    .get("pre_pr_migrator_status", {})
                    .get(migrator_name, "")
                ) or attrs.get("parsing_error", ""):
                    out["bot-error"].add(node)
                    fc = "#000000"
                    fntc = "white"
                else:
                    out["awaiting-parents"].add(node)
                    fc = "#fde725"
        elif "PR" not in pr_json or "state" not in pr_json["PR"]:
            out["bot-error"].add(node)
            fc = "#000000"
            fntc = "white"
        elif pr_is_archiveable:
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
                    feedstock_ctx.git_http_ref,
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
            node_metadata["pre_pr_migrator_status"] = (
                attrs.get("pr_info", {})
                .get(
                    "pre_pr_migrator_status",
                    {},
                )
                .get(migrator_name, "")
            ) or attrs.get("parsing_error", "")
        else:
            node_metadata["pre_pr_migrator_status"] = ""

        if pr_json and "PR" in pr_json:
            # I needed to fake some PRs they don't have html_urls though
            node_metadata["pr_url"] = pr_json["PR"].get(
                "html_url",
                feedstock_ctx.git_http_ref,
            )
            node_metadata["pr_status"] = pr_json["PR"].get("mergeable_state", "")

    # Collect waiting migrators info for creating fake nodes
    waiting_migrators_map: Dict[str, list[str]] = {}
    for node, node_attrs in gx2.nodes.items():
        attrs = node_attrs["payload"]

        # remove archived from status
        if attrs.get("archived", False):
            continue

        # Check if waiting for other migrators
        waiting_migrators = _get_waiting_migrators(migrator, attrs)
        if waiting_migrators:
            waiting_migrators_map[node] = waiting_migrators

    # Add fake migrator nodes and edges after processing regular nodes
    # Create one fake node per waiting migrator PR: migrator_{migrator_name}_{node}_{pr_number}
    # This represents the PR for the waiting migrator on the node itself (not its predecessors)
    fake_migrator_nodes: Dict[str, Dict] = {}

    for node, migrator_names in waiting_migrators_map.items():
        node_attrs = gx2.nodes[node]
        attrs = node_attrs["payload"]

        for migrator_name in migrator_names:
            # Look up the correct migrator instance for the waiting migrator
            # (not the current migrator being processed)
            migrators_by_name = _get_migrators_by_name()
            if migrator_name not in migrators_by_name:
                # Migrator not found, skip
                continue
            waiting_migrator = migrators_by_name[migrator_name]

            # Check if this node has a PR for the waiting migrator
            nuid = waiting_migrator.migrator_uid(attrs)

            nuid_data = frozen_to_json_friendly(nuid)["data"]

            # Look for a matching PR in this node's PRed list
            # No need to copy since we're not modifying the PR data
            matching_pr_json = None
            for pr_json in attrs.get("pr_info", {}).get("PRed", []):
                if pr_json and pr_json.get("data") == nuid_data:
                    matching_pr_json = pr_json
                    break

            if matching_pr_json is None:
                # Node doesn't have a PR for this migrator yet - skip
                continue

            # Get PR data
            pr_data = matching_pr_json.get("PR", {})
            pr_number = pr_data.get("number")
            if pr_number is None:
                continue

            # Create fake node name: migrator_{migrator_name}_{node}_{pr_number}
            # I'm not sure we could have 2 PRs for the same package in another migration,
            # but just to be safe
            fake_parent = f"migrator_{migrator_name}_{node}_{pr_number}"

            # Add fake node to graph if it doesn't exist
            if fake_parent not in gx2.nodes():
                gx2.add_node(fake_parent, payload={})

                pr_url = pr_data.get("html_url", "")
                pr_status = pr_data.get("state", "")

                if not pr_url:
                    feedstock_name = attrs.get("feedstock_name", node)
                    pr_url = f"https://github.com/conda-forge/{feedstock_name}-feedstock/pull/{pr_number}"

                fake_migrator_nodes[fake_parent] = {
                    "pre_pr_migrator_status": "",
                    "pr_url": pr_url,
                    "pr_status": pr_status,
                }
                feedstock_metadata[fake_parent] = fake_migrator_nodes[fake_parent]

                # Set status based on PR state
                if pr_status == "closed":
                    # PR is closed but package is still waiting - this is an error!
                    out["bot-error"].add(fake_parent)
                    print(
                        f"Package '{node}' waiting for migrator '{migrator_name}' but PR #{pr_number} is already closed. "
                        f"Waiting logic may be incorrect.",
                        flush=True,
                    )
                else:
                    # PR is open or in progress
                    out["in-pr"].add(fake_parent)

            # Add edge from fake migrator node to waiting package
            # (migrator blocks package, so migrator -> package)
            if node in gx2.nodes() and not gx2.has_edge(fake_parent, node):
                gx2.add_edge(fake_parent, node)

    # Populate descendants and children for fake migrator nodes (must be done after all edges are added)
    for node_name, node_metadata in fake_migrator_nodes.items():
        node_metadata["num_descendants"] = len(nx.descendants(gx2, node_name))
        node_metadata["immediate_children"] = [
            k
            for k in sorted(gx2.successors(node_name))
            if not gx2[k].get("payload", {}).get("archived", False)
        ]

    out2: Dict = {}
    for k in out.keys():
        # Include all items, even if not in build_sequence (like fake migrator nodes)
        out2[k] = list(
            sorted(
                out[k],
                key=lambda x: (
                    build_sequence.index(x)
                    if x in build_sequence
                    else len(build_sequence),
                    x,
                ),
            ),
        )

    out2["_feedstock_status"] = feedstock_metadata

    for (e0, e1), edge_attrs in gx2.edges.items():
        # Skip edges involving fake migrator nodes - handle separately
        if e0.startswith("migrator_") or e1.startswith("migrator_"):
            continue

        if (
            e0 not in out["done"]
            and e1 not in out["done"]
            and not gx2.nodes[e0]["payload"].get("archived", False)
            and not gx2.nodes[e1]["payload"].get("archived", False)
        ):
            gv.edge(e0, e1)

    # Add nodes and edges for fake migrator parents in visualization
    # (Metadata and awaiting-parents status already added above, before sorting)
    for node_name in gx2.nodes():
        if node_name.startswith("migrator_"):
            migrator_display_name = node_name.replace("migrator_", "")

            # Style migrator nodes differently (awaiting-parents color is #fde725)
            gv.node(
                node_name,
                label=_clean_text(migrator_display_name),
                fillcolor="#fde725",  # Same color as awaiting-parents
                style="filled,dashed",
                fontcolor="black",
            )
            # Add edges from migrator to waiting packages with dashed style
            for successor in gx2.successors(node_name):
                if successor not in out["done"]:
                    gv.edge(node_name, successor, style="dashed", color="orange")

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
            for fut in tqdm.tqdm(as_completed(futs), total=len(futs), ncols=80)
            if fut.result() is not None
        ]


def _compute_recently_closed(total_status, old_closed_status, old_total_status):
    now = int(time.time())
    two_weeks = 14 * 24 * 60 * 60

    # grab any new stuff
    closed_status = {m: now for m in set(old_total_status) - set(total_status)}

    # grab anything recent from previous stuff
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


def main() -> None:
    with fold_log_lines("loading existing status data, graph and migrators"):
        r = requests.get(
            "https://raw.githubusercontent.com/conda-forge/"
            "conda-forge.github.io/77bb24125496/sphinx/img/anvil.svg",
        )

        # cache these for later
        if os.path.exists("status/closed_status.json"):
            with open("status/closed_status.json", "rb") as fp:
                old_closed_status = orjson.loads(fp.read())
        else:
            old_closed_status = {}

        with open("status/total_status.json", "rb") as fp:
            old_total_status = orjson.loads(fp.read())

        smithy_version: str = eval_cmd(["conda", "smithy", "--version"]).strip()
        pinning_version: str = cast(
            str,
            orjson.loads(eval_cmd(["conda", "list", "conda-forge-pinning", "--json"]))[
                0
            ]["version"],
        )
        gx = load_existing_graph()
        mctx = MigratorSessionContext(
            graph=gx,
            smithy_version=smithy_version,
            pinning_version=pinning_version,
        )
        migrators = load_migrators(skip_paused=False)

    os.makedirs("./status/migration_json", exist_ok=True)
    os.makedirs("./status/migration_svg", exist_ok=True)
    regular_status = {}
    longterm_status = {}
    paused_status = {}

    for migrator in migrators:
        # we do not show these on the status page since they are used to
        # open and close migrations
        if isinstance(migrator, MigrationYamlCreator):
            continue

        migrator_name = migrator.report_name

        print(
            "================================================================",
            flush=True,
        )
        print("name:", migrator_name, flush=True)

        if (
            isinstance(migrator, GraphMigrator)
            or isinstance(migrator, Replacement)
            or isinstance(migrator, Migrator)
        ) and not isinstance(migrator, Version):
            if isinstance(migrator, GraphMigrator):
                mgconf = yaml.safe_load(getattr(migrator, "yaml_contents", "{}")).get(
                    "__migrator",
                    {},
                )
                if mgconf.get("paused", False):
                    paused_status[migrator_name] = f"{migrator.name} Migration Status"
                elif (
                    mgconf.get("longterm", False)
                    or isinstance(migrator, ArchRebuild)
                    or isinstance(migrator, OSXArm)
                    or isinstance(migrator, WinArm64)
                ):
                    longterm_status[migrator_name] = f"{migrator.name} Migration Status"
                else:
                    regular_status[migrator_name] = f"{migrator.name} Migration Status"
            else:
                regular_status[migrator_name] = f"{migrator.name} Migration Status"

            status, _, gv = graph_migrator_status(migrator, mctx.graph)
            num_viz = status.pop("_num_viz", 0)
            with open(
                os.path.join(f"./status/migration_json/{migrator_name}.json"),
                "wb",
            ) as fp:
                fp.write(
                    orjson.dumps(
                        status,
                        option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2,
                        default=_sorted_set_json,
                    )
                )

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
                with open(
                    os.path.join(f"./status/migration_svg/{migrator_name}.svg"),
                    "wb",
                ) as fb:
                    fb.write(d or gv.pipe("svg"))
            else:
                with open(
                    os.path.join(f"./status/migration_svg/{migrator_name}.svg"),
                    "wb",
                ) as fb:
                    fb.write(r.content)

        elif isinstance(migrator, Version):
            write_version_migrator_status(migrator, mctx)

        print(" ", flush=True)

    print("writing data", flush=True)
    with open("./status/regular_status.json", "wb") as f:
        f.write(
            orjson.dumps(
                regular_status,
                option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2,
                default=_sorted_set_json,
            )
        )

    with open("./status/longterm_status.json", "wb") as f:
        f.write(
            orjson.dumps(
                longterm_status,
                option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2,
                default=_sorted_set_json,
            )
        )

    with open("./status/paused_status.json", "wb") as f:
        f.write(
            orjson.dumps(
                paused_status,
                option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2,
                default=_sorted_set_json,
            )
        )

    total_status = {}
    total_status.update(regular_status)
    total_status.update(longterm_status)
    total_status.update(paused_status)
    with open("./status/total_status.json", "wb") as f:
        f.write(
            orjson.dumps(
                total_status,
                option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2,
                default=_sorted_set_json,
            )
        )

    closed_status = _compute_recently_closed(
        total_status,
        old_closed_status,
        old_total_status,
    )
    with open("./status/closed_status.json", "wb") as f:
        f.write(
            orjson.dumps(
                closed_status,
                option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2,
                default=_sorted_set_json,
            )
        )

    # remove old status files
    old_files = glob.glob("./status/migration_*/*.*")
    for old_file in old_files:
        mname = os.path.basename(old_file).rsplit(".", 1)[0]
        if (mname not in total_status) and (mname not in closed_status):
            subprocess.run(
                ["git", "rm", "-f", old_file],
                check=True,
            )

    # I have turned this off since we do not use it
    # MRB - 2023/03/08
    """
    print("\ncomputing feedstock and PR stats", flush=True)

    def _get_needs_help(k):
        v = mctx.graph.nodes[k]
        if (
            len(
                [
                    z
                    for z in v.get("payload", {}).get("pr_info", {}).get("PRed", [])
                    if z.get("PR", {}).get("state", "closed") == "open"
                    and z.get("data", {}).get("migrator_name", "") == Version.name
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

    lst = [
        k
        for k, v in mctx.graph.nodes.items()
        if v.get("payload", {}).get("archived", False)
    ]
    with open("./status/archived.json", "w") as f:
        json.dump(sorted(lst), f, indent=2)

    def _get_open_pr_states(k):
        attrs = mctx.graph.nodes[k]["payload"]
        _open_prs = []
        for pr in attrs.get("pr_info", {}).get("PRed", []):
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
    """
