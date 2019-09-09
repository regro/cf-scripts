from conda_forge_tick.utils import load_graph, dump_graph, frozen_to_json_friendly

gx = load_graph()
for k, node_attrs in gx.nodes.items():
    prs = node_attrs.get('PRed', [])
    for i, pr in enumerate(prs):
        pr['data']['bot_rerun'] = False
        pr.update(frozen_to_json_friendly(pr['data']))
dump_graph(gx)
