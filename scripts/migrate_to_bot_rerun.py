from conda_forge_tick.utils import load_graph, dump_graph, frozen_to_json_friendly

gx = load_graph()
for k, node_attrs in gx.nodes.items():
    attrs = node_attrs['payload']
    prs = attrs.get('PRed', [])
    pr: dict
    for i, pr in enumerate(prs):
        pr_data: dict = pr['data']
        pr_data.setdefault('bot_rerun', False)
        prs[i] = frozen_to_json_friendly(pr['data'])
dump_graph(gx)
