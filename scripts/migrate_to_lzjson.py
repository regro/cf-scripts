from conda_forge_tick.utils import LazyJson, load_graph, dump_graph

gx = load_graph()
for k in gx.nodes.keys():
    lzj = LazyJson(f'node_attrs/{k}.json')
    lzj.update(**gx.nodes[k])
    gx.nodes[k].update(lzj)
dump_graph(gx)
