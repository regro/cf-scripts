import networkx as nx

from conda_forge_tick.migrators import Compiler

g = nx.read_gpickle('../cf-graph/graph.pkl')

# Migrate the PRed versions
for node, attrs in g.nodes:
    if 'PRed' in attrs:
        attrs['PRed'] = {'class': 'Version',
                         'class_version': 0,
                         'version': attrs['PRed']}

# Don't migrate already done Compilers (double commits cause problems)
m = Compiler()
compiler_migrations = []
for node, attrs in g.nodes:
    if m.filter(attrs):
        continue
    compiler_migrations.append(node)

last_compiler_pr = 'cxxopts'
last_compiler_index = compiler_migrations.index(last_compiler_pr)
for i in range(last_compiler_index):
    g.nodes[compiler_migrations[i]]['PRed'] = {
        'class': 'Compiler', 'class_version': 0}
