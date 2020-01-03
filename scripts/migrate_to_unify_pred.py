from conda_forge_tick.utils import load_graph, dump_graph, frozen_to_json_friendly
from pprint import pprint

gx = load_graph()
for k, node_attrs in gx.nodes.items():
    if "PRed_json" in node_attrs:
        for pr_json in node_attrs["PRed_json"]:
            if "PR" in pr_json:
                # PRed and PRed_json are the same minus the PR key, so pop it
                # so we can compare things
                pr = pr_json.pop("PR")
                # if for some reason the PR key is in the keys, remove it
                # so we can run the comparison
                if "PR" in pr_json["keys"]:
                    del pr_json["keys"][pr_json["keys"].index("PR")]

                if pr_json in node_attrs["PRed"]:
                    idx = node_attrs["PRed"].index(pr_json)
                else:
                    node_attrs["PRed"].append(pr_json)
                    idx = -1
                # Tack the pr information back on
                node_attrs["PRed"][idx]["PR"] = pr
        del node_attrs["PRed_json"]
dump_graph(gx)
