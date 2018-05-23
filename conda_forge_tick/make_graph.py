import hashlib
import time
import networkx as nx
import requests
from .utils import parsed_meta_yaml
from .all_feedstocks import get_all_feedstocks

import logging

logger = logging.getLogger("conda_forge_tick.make_graph")


def get_attrs(name, i, bad):
    sub_graph = {
        'time': time.time(),
        'feedstock_name': name,
    }

    logger.info((i, name))
    r = requests.get('https://raw.githubusercontent.com/'
                     'conda-forge/{}-feedstock/master/recipe/'
                     'meta.yaml'.format(name))
    if r.status_code != 200:
        logger.warn('Something odd happened when fetching recipe '
                    '{}: {}'.format(name, r.status_code))
        bad.append(name)
        sub_graph['bad'] = r.status_code
        return sub_graph

    text = r.content.decode('utf-8')
    yaml_dict = parsed_meta_yaml(text)
    if not yaml_dict:
        logger.warn('Something odd happened when parsing recipe '
                    '{}'.format(name))
        bad.append(name)
        sub_graph['bad'] = 'Could not parse'
        return sub_graph
    # TODO: Write schema for dict
    req = yaml_dict.get('requirements', set())
    if req:
        build = list(req.get('build', []) if req.get(
            'build', []) is not None else [])
        run = list(req.get('run', []) if req.get(
            'run', []) is not None else [])
        req = build + run
        req = set([x.split()[0] for x in req])

    keys = [('source', 'url'), ('package', 'name'),
            ('package', 'version')]
    missing_keys = [k[1] for k in keys if k[1] not in
                    yaml_dict.get(k[0], {})]
    if missing_keys:
        logger.warn("Recipe {} doesn't have a {}".format(name,
                    ', '.join(missing_keys)))
        bad.append(name)
        sub_graph['bad'] = ', '.join(missing_keys)
        return sub_graph
    sub_graph.update({
        'name': yaml_dict.get('package').get('name'),
        'version': str(yaml_dict.get('package').get('version')),
        'url': yaml_dict.get('source').get('url'),
        'req': req,
        'time': time.time(),
        'feedstock_name': name,
        'meta_yaml': yaml_dict,
        'raw_meta_yaml': text,
    })
    k = next(iter((set(yaml_dict['source'].keys()) &
                   hashlib.algorithms_available)), None)
    if k:
        sub_graph['hash_type'] = k

    return sub_graph


def make_graph(names, gx=None):

    bad = []

    logger.info('reading graph')

    if gx is None:
        gx = nx.DiGraph()

    new_names = [name for name in names if name not in gx.nodes]
    old_names = [name for name in names if name in gx.nodes]
    old_names = sorted(old_names, key=lambda n: gx.nodes[n]['time'])

    total_names = new_names + old_names
    logger.info('start loop')

    for i, name in enumerate(total_names):
        try:
            sub_graph = get_attrs(name, i, bad)
        except Exception as e:
            logger.warn('Error adding {} to the graph: {}'.format(name, e))
        else:
            if name in new_names:
                gx.add_node(name, **sub_graph)
            else:
                gx.nodes[name].update(**sub_graph)

    for node, attrs in gx.node.items():
        for dep in attrs.get('req', []):
            if dep in gx.nodes:
                gx.add_edge(dep, node)
    return gx, bad


def main(*args, **kwargs):
    logging.basicConfig(level=logging.ERROR)
    logger.setLevel(logging.INFO)
    names = get_all_feedstocks(cached=True)
    gx = nx.read_gpickle('graph.pkl')
    gx, bad = make_graph(names, gx)

    logger.info('writing out file')
    with open('bad.txt', 'w') as f:
        f.write('\n'.join(bad))
    nx.write_gpickle(gx, 'graph.pkl')


if __name__ == "__main__":
    main()
