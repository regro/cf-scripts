from conda_forge_tick.utils import load_graph
from conda_forge_tick.update_upstream_versions import (
    get_latest_version,
    PyPI,
    CRAN,
    NPM,
    ROSDistro,
    RawURL,
    Github,
)
import random
import json

sources = (PyPI(), CRAN(), NPM(), ROSDistro(), RawURL(), Github())

# Reading graph
gx = load_graph()
_all_nodes = [t for t in gx.nodes.items()]
random.shuffle(_all_nodes)

# Inspection the graph object and node update:
# print(f"Number of nodes: {len(gx.nodes)}")
Node_count = 0

to_update = {}
to_update["nodes"] = []
for node, node_attrs in _all_nodes:
    # checking each node
    with node_attrs["payload"] as attrs:
        # verify the actual situation of the package;
        actual_ver = str(attrs.get("version"))
        if attrs.get("bad") or attrs.get("archived"):
            print(
                f"# {Node_count:<5} - {node:<30} - ver: {actual_ver:<10} - bad/archived"
            )
            Node_count += 1
            continue
        # New verison request
        try:
            new_version = get_latest_version(node, attrs, sources)
        except Exception as e:
            try:
                se = repr(e)
            except Exception as ee:
                se = "Bad exception string: {}".format(ee)
                print(f"Warning: Error getting upstream version of {node}: {se}")
        else:
            print(
                f"# {Node_count:<5} - {node:<30} - ver: {attrs.get('version'):<10} - new ver: {new_version}"
            )
        to_update["nodes"].append({"id": str(node), "version": str(new_version)})
    Node_count += 1

# Writing  out file
with open("new_version.json", "w") as outfile:
    json.dump(to_update, outfile)
