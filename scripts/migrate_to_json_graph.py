import networkx as nx
from conda_forge_tick.utils import dump_graph
gx = nx.read_gpickle('graph.pkl')

dump_graph(gx, 'graph.json')
