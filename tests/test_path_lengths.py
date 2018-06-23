from conda_forge_tick.path_lengths import get_levels, nx


def test_get_levels():
    g = nx.DiGraph(
        [
            ("a", "d"),
            ("b", "d"),
            ("b", "e"),
            ("c", "e"),
            ("c", "h"),
            ("d", "f"),
            ("d", "g"),
            ("d", "h"),
            ("e", "g"),
        ]
    )
    levels = {0: {"a"}, 1: {"d"}, 2: {"f", "g", "h"}}
    assert get_levels(g, "a") == levels

    g.add_edges_from([("a", "b"), ("e", "a")])
    levels = {0: {"a"}, 1: {"b"}, 2: {"d", "e"}, 3: {"f", "g", "h"}}
    assert get_levels(g, "a") == levels

    g.add_edge("d", "c")
    levels = {0: {"a"}, 1: {"b"}, 2: {"d"}, 3: {"c", "f"}, 4: {"e", "h"}, 5: {"g"}}
    assert get_levels(g, "a") == levels
