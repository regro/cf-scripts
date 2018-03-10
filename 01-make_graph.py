import codecs
import datetime
import hashlib
import os
import re
import time
from base64 import b64decode
from collections import defaultdict

import networkx as nx
import requests
import jinja2

from conda_build.metadata import parse
from conda_build.config import Config


class NullUndefined(jinja2.Undefined):
    def __unicode__(self):
        return self._undefined_name

    def __getattr__(self, name):
        return '{}.{}'.format(self, name)

    def __getitem__(self, name):
        return '{}["{}"]'.format(self, name)


env = jinja2.Environment(undefined=NullUndefined)

def parsed_meta_yaml(text):
    """
    :param str text: The raw text in conda-forge feedstock meta.yaml file
    :return: `dict|None` -- parsed YAML dict if successful, None if not
    """
    try:
        content = env.from_string(text).render(os=os, environ=defaultdict(lambda : ''))
        return parse(content, Config())
    except:
        return {}


# TODO: with names in a graph
print('reading names')
with open('names.txt', 'r') as f:
    names = f.read().split()

new_bad = []

print('reading graph')
gx = nx.read_gpickle('graph.pkl')
# gx = nx.read_yaml('graph.yml')

new_names = [name for name in names if
             name not in gx.nodes]
old_names = [name for name in names if name in gx.nodes]
old_names = sorted(old_names, key=lambda n: gx.nodes[n]['time'])

total_names = new_names + old_names
print('start loop')

for i, name in enumerate(total_names):
    print(i, name)
    r = requests.get('https://raw.githubusercontent.com/conda-forge/'
                     '{}-feedstock/master/recipe/meta.yaml'.format(name))
    if r.status_code != 200:
        print('Something odd happened to this recipe '
              '{}'.format(r.status_code))
        new_bad.append(name)
        continue

    text = r.content.decode('utf-8')
    yaml_dict = parsed_meta_yaml(text)
    if not yaml_dict:
        new_bad.append(name)
        continue
    # TODO: Write schema for dict
    req = yaml_dict.get('requirements', set())
    if req:
        build = list(req.get('build', []) if req.get(
            'build', []) is not None else [])
        run = list(req.get('run', []) if req.get(
            'run', []) is not None else [])
        req = build + run
        req = set([x.split()[0] for x in req])

    if not ('url' in yaml_dict.get('source', {})
            and 'name' in yaml_dict.get('package', {})
            and 'version' in yaml_dict.get('package', {})):
        new_bad.append(name)
        continue
    sub_graph = {
        'name': yaml_dict['package']['name'],
        'version': str(yaml_dict['package']['version']),
        'url': yaml_dict['source']['url'],
        'req': req,
        'time': time.time(),
        'feedstock_name': name,
        'meta_yaml': yaml_dict,
        'raw_meta_yaml': text,
    }
    k = next(iter((set(yaml_dict['source'].keys())
                      & hashlib.algorithms_available)), None)
    if k:
        sub_graph['hash_type'] = k

    if name in new_names:
        gx.add_node(name, **sub_graph)
    else:
        gx.nodes[name].update(**sub_graph)
    # nx.write_yaml(gx, 'graph.yml')
    nx.write_gpickle(gx, 'graph.pkl')

for node, attrs in gx.node.items():
    for dep in attrs['req']:
        if dep in gx.nodes:
            gx.add_edge(dep, node)
print('writing out file')
with open('bad.txt', 'w') as f:
    f.write('\n'.join(new_bad))
# nx.write_yaml(gx, 'graph.yml')
nx.write_gpickle(gx, 'graph.pkl')
