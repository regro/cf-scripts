# type this code in at the interpreter
from conda_forge_tick.utils import load_graph

gx = utils.load_graph()

# from here you can inspect the graph object
print("# of nodes:", len(gx.nodes))
with gx.nodes['python']['payload']['meta_yalm'] as attrs:
    for i in attrs:
        print(i)