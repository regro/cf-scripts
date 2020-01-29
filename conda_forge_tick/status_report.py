from .auto_tick import initialize_migrators, migrator_status
import os
import json
import networkx as nx
import subprocess

from graphviz import Source
import tempfile

from typing import Any

from conda_forge_tick.migrators import GraphMigrator, LicenseMigrator, Version


def main(args: Any = None) -> None:
    mctx, *_, migrators = initialize_migrators()
    if not os.path.exists("./status"):
        os.mkdir("./status")
    total_status = {}

    for migrator in migrators:
        if isinstance(migrator, GraphMigrator):
            migrator_name = migrator.__class__.__name__.lower()
            if migrator_name in ["rebuild", "migrationyaml"]:
                assert isinstance(migrator.name, str)
                migrator_name = migrator.name.lower().replace(" ", "")
            total_status[migrator_name] = f"{migrator.name} Migration Status"
            status, build_order, gv = migrator_status(migrator, mctx.graph)
            with open(os.path.join(f"./status/{migrator_name}.json"), "w") as fo:
                json.dump(status, fo, indent=2)

            d = gv.pipe("dot")
            with tempfile.NamedTemporaryFile() as ntf, open(
                f"{ntf.name}.dot", "w"
            ) as f:
                f.write(d.decode("utf-8"))
                # make the graph a bit more compact
                d = Source(
                    subprocess.check_output(
                        ["unflatten", "-f", "-l", "5", "-c", "10", f"{ntf.name}.dot"]
                    ).decode("utf-8")
                ).pipe("svg")
            with open(os.path.join(f"./status/{migrator_name}.svg"), "wb") as fb:
                fb.write(d)

    with open("./status/total_status.json", "w") as f:
        json.dump(total_status, f, sort_keys=True)
    l = [
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
                l, key=lambda z: (len(nx.descendants(mctx.graph, z)), l), reverse=True,
            ),
            f,
            indent=2,
        )

    lm = LicenseMigrator()
    l = [k for k, v in mctx.graph.nodes.items() if not lm.filter(v.get("payload", {}))]
    with open("./status/unlicensed.json", "w") as f:
        json.dump(
            sorted(
                l, key=lambda z: (len(nx.descendants(mctx.graph, z)), l), reverse=True,
            ),
            f,
            indent=2,
        )


if __name__ == "__main__":
    main()
