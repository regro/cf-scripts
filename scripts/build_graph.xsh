import networkx as nx
import copy
from conda_forge_tick.path_lengths import cyclic_topological_sort, get_levels
from conda_forge_tick.utils import pluck

gx = nx.read_gpickle('graph.pkl')
total_graph = copy.deepcopy(gx)

compilers = {'toolchain', 'gcc', 'cython', 'pkg-config',
             'autotools', 'make', 'cmake', 'autconf', 'libtool', 'm4',
             'ninja', 'jom', 'libgcc', 'libgfortran'}


def _build_host(req):
    rv = set(
        (req.get('host', []) or []) +
        (req.get('build', []) or [])
    )
    if None in rv:
        rv.remove(None)
    return rv


for node, attrs in gx.node.items():
    req = attrs.get('meta_yaml', {}).get('requirements', {})
    bh = _build_host(req)

    py_c = ('python' in bh and (attrs.get('meta_yaml', {}).get('build', {}).get('noarch') == 'python'))
    com_c = (any([req.endswith('_compiler_stub') for req in bh])
             or any([a in bh for a in compilers]))
    r_c = 'r-base' in bh
    ob_c = 'openblas' in bh
    if not any([py_c, com_c, r_c, ob_c]):
        pluck(total_graph, node)
    total_graph.remove_edges_from(node)
    if 'host' in attrs.get('meta_yaml', {}):
        rq = attrs.get('meta_yaml').get('host')
    else:
        rq = attrs.get('meta_yaml').get('build')
    total_graph.remove_edges_from(node)
    for r in rq:
        total_graph.add_edge(r, node)


top_level = set(node for node in total_graph if not list(total_graph.predecessors(node)))
z = cyclic_topological_sort(total_graph, top_level)

levels = get_levels(total_graph, 'zlib')
