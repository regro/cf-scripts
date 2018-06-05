import os

from conda_forge_tick.path_lengths import get_levels


def test_get_levels():
    d = os.path.join(os.getcwd(), os.path.dirname(__file__))

    levels = {0: {'a'}, 1: {'d'}, 2: {'f', 'g', 'h'}}
    assert get_levels(os.path.join(d, 'test_graph1.pkl'), 'a') == levels

    levels = {0: {'a'}, 1: {'b'}, 2: {'d', 'e'}, 3: {'f', 'g', 'h'}}
    assert get_levels(os.path.join(d, 'test_graph2.pkl'), 'a') == levels

    levels = {0: {'a'}, 1: {'b'}, 2: {'d'}, 3: {'c', 'f'},
              4: {'e', 'h'}, 5: {'g'}}
    assert get_levels(os.path.join(d, 'test_graph3.pkl'), 'a') == levels
