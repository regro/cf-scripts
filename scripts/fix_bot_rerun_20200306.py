from conda_forge_tick.utils import load_graph, dump_graph_json

gx = load_graph()
for node in gx.nodes:
    with gx.nodes[node]["payload"] as node_attrs:
        prs = node_attrs.get("PRed", [])
        for i, pr in enumerate(prs):
            if "bot_rerun" in pr:
                print("fixing:", node)
                pr["data"]["bot_rerun"] = pr["bot_rerun"]
                del pr["bot_rerun"]

dump_graph_json(gx, "graph.json")
