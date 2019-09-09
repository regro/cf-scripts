from conda_forge_tick.utils import load_graph, dump_graph

gx = load_graph()
for k, node_attrs in gx.nodes.items():
    if 'PRed_json' in node_attrs:
        for pr_json in node_attrs['PRed_json']:
            if 'PR' in pr_json:
                pr = pr_json.pop('PR')
                if pr in node_attrs['PRed']:
                    idx = node_attrs['PRed'].index(pr)
                else:
                    node_attrs['PRed'].append(pr_json)
                    idx = -1
                node_attrs['PRed'][idx]['PR'] = pr
        del node_attrs['PRed_json']
dump_graph(gx)
