import networkx as nx

g = nx.read_gpickle('graph.pkl')
with open('cycles.txt', 'w') as f:
    for cyc in nx.simple_cycles(g):
        f.write(str(cyc) + '\n')
