from conda_forge_tick.utils import LazyJson


import networkx as nx
gx = nx.read_gpickle('graph.pkl')
for k in gx.nodes.keys():
    lzj = LazyJson(f'node_attrs/{k}.json')
    lzj.update(**gx.nodes[k])
    gx.nodes[k] = lzj
nx.write_gpickle(gx, 'graph.pkl')
