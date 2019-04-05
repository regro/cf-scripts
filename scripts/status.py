import networkx as nx
from pkg_resources import parse_version


def pv(v):
    if not v:
        v = "0.0.0"
    return parse_version(v.replace("_", "."))


g = nx.read_gpickle("graph.pkl")

a = [
    n
    for n, a in g.node.items()
    if a.get("new_version", False)
    and pv(a["new_version"]) > pv(a["version"])
    and pv(a.get("PRed", "0.0.0")) < pv(a["new_version"])
    and a.get("archived", False) is False
]
print("packages out of date and not PRed: {}".format(len(a)))
for b in a:
    print(
        b, g.node[b]["version"], g.node[b]["new_version"], g.node[b].get("PRed", None)
    )

print(
    "packages of unknown upstream: {}".format(
        len([n for n, a in g.node.items() if a.get("new_version", True) == False])
    )
)
