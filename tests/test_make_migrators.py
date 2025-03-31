import os
import subprocess
import tempfile

import networkx as nx

from conda_forge_tick.lazy_json_backends import lazy_json_override_backends
from conda_forge_tick.make_migrators import (
    dump_migrators,
    initialize_migrators,
    load_migrators,
)
from conda_forge_tick.migrators import MigrationYaml
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import load_graph, pluck


def test_make_migrators_initialize_migrators():
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                "https://github.com/regro/cf-graph-countyfair.git",
            ],
            cwd=tmpdir,
            check=True,
        )
        with (
            pushd(os.path.join(tmpdir, "cf-graph-countyfair")),
            lazy_json_override_backends(["file"], use_file_cache=True),
        ):
            gx = load_graph()

            assert "payload" in gx.nodes["conda-forge-pinning"], (
                "Payload not found for conda-forge-pinning!"
            )

            nodes_to_keep = set()
            # random selection of packages to cut the graph down
            nodes_to_test = [
                "ngmix",
                "ultraplot",
                "r-semaphore",
                "r-tidyverse",
                "conda-forge-pinning",
            ]
            while nodes_to_test:
                pkg = nodes_to_test.pop(0)
                if pkg in gx.nodes:
                    nodes_to_keep.add(pkg)
                    for n in gx.predecessors(pkg):
                        if n not in nodes_to_keep:
                            nodes_to_test.append(n)

            for pkg in set(gx.nodes) - nodes_to_keep:
                pluck(gx, pkg)

            # post plucking cleanup
            gx.remove_edges_from(nx.selfloop_edges(gx))

            print(
                "Number of nodes in the graph after plucking:",
                len(gx.nodes),
                flush=True,
            )

            migrators = initialize_migrators(gx)

            assert len(migrators) > 0, "No migrators found!"
            for migrator in migrators:
                assert migrator is not None, "Migrator is None!"
                assert hasattr(migrator, "effective_graph"), (
                    "Migrator has no effective graph!"
                )
                assert hasattr(migrator, "graph"), "Migrator has no graph attribute!"
                if isinstance(migrator, MigrationYaml):
                    assert "conda-forge-pinning" in migrator.graph.nodes

            # dump and load the migrators
            dump_migrators(migrators)
            load_migrators(skip_paused=False)
