import networkx as nx

g = nx.read_yaml('graph.yml')
with open('cycles.txt', 'w') as f:
    for cyc in nx.simple_cycles(g):
        f.write(str(cyc) + '\n')
