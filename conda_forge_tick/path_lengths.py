from copy import deepcopy

import networkx as nx


def cyclic_topological_sort(graph, source):
    order = []
    visit(graph, source, order)
    return reversed(order)


def _visit(graph, node, order):
    if graph.node[node].get('visited', False):
        return
    graph.node[node]['visited'] = True
    for n in graph.neighbors(node):
        visit(graph, n, order)
    order.append(node)


def get_longest_paths(graph, source):
    dist = {node: -float('inf') for node in graph}
    dist[source] = 0
    for u in cyclic_topological_sort(graph, source):
        for v in graph.neighbors(u):
            if dist[v] < dist[u] + 1:
                dist[v] = dist[u] + 1

    return dist


def get_levels(graph_file, source):
    g = nx.read_gpickle(graph_file)
    g2 = deepcopy(g)
    desc = nx.algorithms.descendants(g, source)
    for node in g.node:
        if (node not in desc and node != source):
            g2.remove_node(node)

    dist = get_longest_paths(g2, source)
    return {v: [k for k in dist if dist[k] == v] for v in dist.values()}
