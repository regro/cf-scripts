from conda_forge_tick.path_lengths import get_levels

def test_get_levels():
    levels = {0: {'a'}, 1: {'d'}, 2: {'f', 'g', 'h'}}
    assert get_levels('test_graph1.pkl', 'a') == levels

    levels = {0: {'a'}, 1: {'b'}, 2: {'d', 'e'}, 3: {'f', 'g', 'h'}}
    print(get_levels('test_graph2.pkl', 'a'))
    assert get_levels('test_graph2.pkl', 'a') == levels

    levels = {0: {'a'}, 1: {'b'}, 2: {'d'}, 3: {'c', 'f'}, 4: {'e', 'h'}, 5: {'g'}}
    print(get_levels('test_graph3.pkl', 'a'))
    assert get_levels('test_graph3.pkl', 'a') == levels

test_get_levels()
