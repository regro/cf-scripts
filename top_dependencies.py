import networkx as nx

g = nx.read_gpickle("graph.pkl")
order = [(node, len(nx.descendants(g, node))) for node in g.nodes]
order.sort(key=lambda x: x[1], reverse=True)

space = max([len(x[0]) for x in order[:100]])
space = max(space, len("package"))
lines = ["{0:<{2}}{1:>21}".format(*x, space) for x in order[:100]]

with open("top_100.txt", "w") as f:
    f.write("{0:<{2}}{1}\n".format("Package", "Number of Descendants", space))
    f.write("\n".join(lines))
