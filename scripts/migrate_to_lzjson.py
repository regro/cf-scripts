from conda_forge_tick.utils import load_graph, dump_graph
from conda_forge_tick.lazy_json_backends import LazyJson

gx = load_graph()
for k in gx.nodes.keys():
    lzj = LazyJson(f"node_attrs/{k}.json")
    lzj.update(**gx.nodes[k])
    gx.nodes[k].clear()
    gx.nodes[k].update({"payload": lzj})
dump_graph(gx)
