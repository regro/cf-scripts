#!/usr/bin/env python
import networkx as nx

from conda_forge_tick.migrators import Compiler

g = nx.read_gpickle("../cf-graph/graph.pkl")

# Migrate the PRed versions
for node, attrs in g.nodes.items():
    if attrs.get("PRed", False):
        attrs["PRed"] = [
            {
                "migrator_name": "Version",
                "migrator_version": 0,
                "version": attrs["PRed"],
            }
        ]
    elif "PRed" in attrs:
        attrs["PRed"] = []


# Don't migrate already done Compilers (double commits cause problems)
m = Compiler()
compiler_migrations = []
for node, attrs in g.nodes.items():
    if m.filter(attrs):
        continue
    compiler_migrations.append(node)

last_compiler_pr = "cxxopts"
last_compiler_index = compiler_migrations.index(last_compiler_pr)
for i in range(last_compiler_index):
    attrs = g.nodes[compiler_migrations[i]]
    attrs.setdefault("PRed", []).append(
        {"migrator_name": "Compiler", "migrator_version": 0}
    )

nx.write_gpickle(g, "../cf-graph/graph.pkl")
