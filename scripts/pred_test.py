import networkx as nx

g = nx.read_gpickle("graph.pkl")
pred = [n for n, attrs in g.node.items() if "PRed" in attrs]
assert len(pred) >= 1
