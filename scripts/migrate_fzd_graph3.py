from conda_forge_tick.utils import frozen_to_json_friendly


def migrate(d: dict):
    pred = d.get("PRed", None)
    if pred:
        l = []
        for element in d["PRed"]:
            l.append(frozen_to_json_friendly(element))
        d["PRed"] = l

    pred_json = d.get("PRed_json", None)
    if pred_json:
        l = []
        for element, pr in d["PRed_json"].items():
            l.append(frozen_to_json_friendly(element, pr))
        d["PRed_json"] = l


import networkx as nx

gx = nx.read_gpickle("graph.pkl")
for d in gx.nodes.values():
    migrate(d)
nx.write_gpickle(gx, "graph.pkl")
