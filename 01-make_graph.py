import codecs
import datetime
import os
import re
import time
from base64 import b64decode

import github3
import networkx as nx
import yaml
from jinja2 import UndefinedError, Template


def parsed_meta_yaml(text):
    """
    :param str text: The raw text in conda-forge feedstock meta.yaml file
    :return: `dict|None` -- parsed YAML dict if successful, None if not
    """
    try:
        yaml_dict = yaml.load(Template(text).render())
    except UndefinedError:
        # assume we hit a RECIPE_DIR reference in the vars and can't parse it.
        # just erase for now
        try:
            yaml_dict = yaml.load(
                Template(
                    re.sub('{{ (environ\[")?RECIPE_DIR("])? }}/', '',
                           text)
                ).render())
        except Exception as e:
            print(e)
            return None
    except Exception as e:
        print(e)
        return None

    return yaml_dict


def source_location(meta_yaml):
    try:
        if 'github.com' in meta_yaml['source']['url']:
            return 'github'
        elif 'pypi.python.org' in meta_yaml['source']['url']:
            return 'pypi'
        else:
            return None
    except KeyError:
        return None


# TODO: with names in a graph
print('reading names')
with open('names.txt', 'r') as f:
    names = f.read().split()

print('reading bad')
with open('bad.txt', 'r') as f:
    bad = set(f.read().split())

print(bad)
print('reading graph')
gx = nx.read_gpickle('graph.pkl')
# gx = nx.read_yaml('graph.yml')

new_names = [name for name in names if name not in gx.nodes and name not in bad]
old_names = [name for name in names if name in gx.nodes]
old_names = sorted(old_names, key=lambda n: gx.nodes[n]['time'])

total_names = new_names + old_names
print('start loop')
gh = github3.login(os.environ['USERNAME'], os.environ['PASSWORD'])
try:
    for i, name in enumerate(total_names):
        print(i, name)
        feedstock = gh.repository('conda-forge', name + '-feedstock')
        meta_yaml = feedstock.contents('recipe/meta.yaml')
        if meta_yaml:
            text = codecs.decode(b64decode(meta_yaml.content))
            a = parsed_meta_yaml(text)
            if not a:
                with open('bad.txt', 'a') as f:
                    f.write('{}\n'.format(name))
                continue
            yaml_dict = a
            # TODO: Write schema for dict
            if yaml_dict:
                req = yaml_dict.get('requirements', set())
                if req:
                    build = req.get('build', []) if req.get('build', []) is not None else []
                    run = req.get('run', []) if req.get('run', []) is not None else []
                    req = build + run
                    req = set([x.split()[0] for x in req])

                if not ('url' in yaml_dict.get('source', {})
                    and 'name' in yaml_dict.get('package', {})
                    and 'version' in yaml_dict.get('package', {})):
                    with open('bad.txt', 'a') as f:
                        f.write('{}\n'.format(name))
                    continue
                sub_graph = {
                    'name': yaml_dict['package']['name'],
                    'version': str(yaml_dict['package']['version']),
                    'url': yaml_dict['source']['url'],
                    'req': req,
                    'time': time.time(),
                }

                if name in new_names:
                    gx.add_node(name, **sub_graph)
                else:
                    gx.nodes[name].update(**sub_graph)
                # nx.write_yaml(gx, 'graph.yml')
                nx.write_gpickle(gx, 'graph.pkl')

except github3.GitHubError as e:
    print(e)
    c = gh.rate_limit()['resources']['core']
    if c['remaining'] == 0:
        ts = c['reset']
        print('API timeout, API returns at')
        print(datetime.datetime.utcfromtimestamp(ts)
              .strftime('%Y-%m-%dT%H:%M:%SZ'))
    pass
for node, attrs in gx.node.items():
    for dep in attrs['req']:
        if dep in gx.nodes:
            gx.add_edge(dep, node)
print('writing out file')
# nx.write_yaml(gx, 'graph.yml')
nx.write_gpickle(gx, 'graph.pkl')
