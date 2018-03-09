"""Copyright (c) 2017, Anthony Scopatz"""
import copy
import datetime
import os
import re
import time
import traceback
import urllib.error

import github3
import networkx as nx
import yaml
from doctr.travis import run as doctr_run
from jinja2 import UndefinedError, Template
from pkg_resources import parse_version
from rever.tools import (eval_version, indir, hash_url, replace_in_file)
from conda_build.metadata import parse
from conda_build.config import Config


def parsed_meta_yaml(text):
    """
    :param str text: The raw text in conda-forge feedstock meta.yaml file
    :return: `dict|None` -- parsed YAML dict if successful, None if not
    """
    try:
        yaml_dict = parse(Template(text).render(), Config())
    except UndefinedError:
        # assume we hit a RECIPE_DIR reference in the vars and can't parse it.
        # just erase for now
        try:
            yaml_dict = parse(
                Template(
                    re.sub('{{ (environ\[")?RECIPE_DIR("])? }}/', '',
                           text)
                ).render(), Config())
        except Exception as e:
            print(e)
            return None
    except Exception as e:
        print(e)
        return None

    return yaml_dict


def feedstock_url(feedstock, protocol='ssh'):
    """Returns the URL for a conda-forge feedstock."""
    if feedstock is None:
        feedstock = $PROJECT + '-feedstock'
    elif feedstock.startswith('http://github.com/'):
        return feedstock
    elif feedstock.startswith('https://github.com/'):
        return feedstock
    elif feedstock.startswith('git@github.com:'):
        return feedstock
    protocol = protocol.lower()
    if protocol == 'http':
        url = 'http://github.com/conda-forge/' + feedstock + '.git'
    elif protocol == 'https':
        url = 'https://github.com/conda-forge/' + feedstock + '.git'
    elif protocol == 'ssh':
        url = 'git@github.com:conda-forge/' + feedstock + '.git'
    else:
        msg = 'Unrecognized github protocol {0!r}, must be ssh, http, or https.'
        raise ValueError(msg.format(protocol))
    return url


def feedstock_repo(feedstock):
    """Gets the name of the feedstock repository."""
    if feedstock is None:
        repo = $PROJECT + '-feedstock'
    else:
        repo = feedstock
    repo = repo.rsplit('/', 1)[-1]
    if repo.endswith('.git'):
        repo = repo[:-4]
    return repo


def fork_url(feedstock_url, username):
    """Creates the URL of the user's fork."""
    beg, end = feedstock_url.rsplit('/', 1)
    beg = beg[:-11]  # chop off 'conda-forge'
    url = beg + username + '/' + end
    return url


DEFAULT_PATTERNS = (
    # filename, pattern, new
    # set the version
    ('meta.yaml', '  version:\s*[A-Za-z0-9._-]+', '  version: "$VERSION"'),
    ('meta.yaml', '{% set version = ".*" %}', '{% set version = "$VERSION" %}'),
    ('meta.yaml', "{% set version = '.*' %}", '{% set version = "$VERSION" %}'),
    ('meta.yaml', '{% set version = .* %}', '{% set version = "$VERSION" %}'),
    ('meta.yaml', '{%set version = ".*" %}', '{%set version = "$VERSION" %}'),
    # reset the build number to 0
    ('meta.yaml', '  number:.*', '  number: 0'),
    # set the hash
    ('meta.yaml', '{% set $HASH_TYPE = "[0-9A-Fa-f]+" %}',
                  '{% set $HASH_TYPE = "$HASH" %}'),
    ('meta.yaml', '  $HASH_TYPE:\s*[0-9A-Fa-f]+', '  $HASH_TYPE: $HASH'),

    )

more_patterns = []
checksum_names = ['hash_value', 'hash', 'hash_val', 'sha256sum', 'checksum',
                  '$HASH_TYPE']
delim = ["'", '"']
sets = [' set', 'set']
base1 = '''{{%{set} {checkname} = {d}[0-9A-Fa-f]+{d} %}}'''
base2 = '''{{%{set} {checkname} = {d}$HASH{d} %}}'''
for cn in checksum_names:
    for s in sets:
        for d in delim:
            more_patterns.append(('meta.yaml',
                                  base1.format(set=s, checkname=cn, d=d),
                                  base2.format(set=s, checkname=cn, d=d)))


def run(feedstock=None, protocol='ssh',
        hash_type='sha256', patterns=DEFAULT_PATTERNS,
        pull_request=True, rerender=True, fork=True, pred=None, gh=None):
    if pred is None:
        pred = []
    if gh is None:
        gh = github3.login($USERNAME, $PASSWORD)
        # first, let's grab the feedstock locally
    upstream = feedstock_url(feedstock, protocol=protocol)
    origin = fork_url(upstream, $USERNAME)
    feedstock_reponame = feedstock_repo(feedstock)

    if pull_request or fork:
        repo = gh.repository('conda-forge', feedstock_reponame)

    # Check if fork exists
    if fork:
        fork_repo = gh.repository($USERNAME, feedstock_reponame)
        if fork_repo is None or (hasattr(fork_repo, 'is_null') and
                                 fork_repo.is_null()):
            print("Fork doesn't exist creating feedstock fork...")
            repo.create_fork()
            # Sleep to make sure the fork is created before we go after it
            time.sleep(5)

    feedstock_dir = os.path.join($REVER_DIR, $PROJECT + '-feedstock')
    recipe_dir = os.path.join(feedstock_dir, 'recipe')
    if not os.path.isdir(feedstock_dir):
        p = ![git clone @(origin) @(feedstock_dir)]
        if p.rtn != 0:
            msg = 'Could not clone ' + origin
            msg += '. Do you have a personal fork of the feedstock?'
            return
    with indir(feedstock_dir):
        git fetch @(origin)
        # make sure feedstock is up-to-date with origin
        git checkout master
        git pull @(origin) master
        # make sure feedstock is up-to-date with upstream
        git pull @(upstream) master
        # make and modify version branch
        with ${...}.swap(RAISE_SUBPROC_ERROR=False):
            git checkout $VERSION or git checkout -b $VERSION master
    # Render with new version but nothing else
    with indir(recipe_dir):
        for f, p, n in patterns:
            p = eval_version(p)
            n = eval_version(n)
            replace_in_file(p, n, f)
        with open('meta.yaml', 'r') as f:
            text = f.read()
        # If we can't parse the meta_yaml then jump out
        meta_yaml = parsed_meta_yaml(text)
        if meta_yaml is None:
            with open('bad.txt', 'a') as f:
                f.write('{}\n'.format($PROJECT))
            return False
        source_url = meta_yaml['source']['url']

    # now, update the feedstock to the new version
    source_url = eval_version(source_url)
    try:
        hash = hash_url(source_url, hash_type)
    except urllib.error.HTTPError:
        with open('upstream_bad', 'a') as f:
            f.write('{}: hash failed\n'.format(meta_yaml['name']))

    patterns += tuple(more_patterns)
    with indir(recipe_dir), ${...}.swap(HASH_TYPE=hash_type, HASH=hash,
                                        SOURCE_URL=source_url):
        for f, p, n in patterns:
            p = eval_version(p)
            n = eval_version(n)
            replace_in_file(p, n, f)
    with indir(feedstock_dir), ${...}.swap(RAISE_SUBPROC_ERROR=False):
        git commit -am @("updated v" + $VERSION)
        if rerender:
            print('Rerendering the feedstock')
            conda smithy rerender -c auto

        # Setup push from doctr
        '''Copyright (c) 2016 Aaron Meurer, Gil Forsyth '''
        token = $PASSWORD
        deploy_repo = $USERNAME + '/' + $PROJECT + '-feedstock'
        doctr_run(['git', 'remote', 'add', 'regro_remote',
             'https://{token}@github.com/{deploy_repo}.git'.format(
                 token=token,
                 deploy_repo=deploy_repo)])

        git push --set-upstream regro_remote $VERSION
    # lastly make a PR for the feedstock
    if not pull_request:
        return
    print('Creating conda-forge feedstock pull request...')
    title = $PROJECT + ' v' + $VERSION
    head = $USERNAME + ':' + $VERSION
    body = ('Merge only after success.\n\n'
            'This PR was created by [regro auto-tick](https://github.com/regro/cf-scripts). '
            'Please let the devs know if there are any [issues](https://github.com/regro/cf-scripts/issues). '
            "Please feel free to push to the bot's branch to update this PR. \n\n")
    # Statement here
    template = '|{name}|{new_version}|[![Anaconda-Server Badge](https://anaconda.org/conda-forge/{name}/badges/version.svg)](https://anaconda.org/conda-forge/{name})|\n'
    if len(pred) > 0:
        body += ('Here is a list of all the pending dependencies (and their '
                 'versions) for this repo. '
                 'Please double check all dependencies before merging.\n\n')
        # Only add the header row if we have content. Otherwise the rendered table in the github comment
        # is empty which is confusing
        body += '''| Name | Upstream Version | Current Version |\n|:----:|:----------------:|:---------------:|\n'''
    for p in pred:
        body += template.format(name=p[0], new_version=p[1])
    pr = repo.create_pull(title, 'master', head, body=body)
    if pr is None:
        print('Failed to create pull request!')
    else:
        print('Pull request created at ' + pr.html_url)
    print('Removing feedstock dir')
    rm -rf @(feedstock_dir)
    return True

# gx = nx.read_yaml('graph.yml')
gx = nx.read_gpickle('graph.pkl')
gx2 = copy.deepcopy(gx)

# Prune graph to only things that need builds
for node, attrs in gx.node.items():
    if not attrs['new_version']:
        gx2.remove_node(node)
    elif parse_version(str(attrs['new_version'])) <= parse_version(str(attrs['version'])):
        gx2.remove_node(node)

$REVER_DIR = './feedstocks/'
gh = github3.login($USERNAME, $PASSWORD)

t0 = time.time()
for node, attrs in gx2.node.items():
    # Don't let travis timeout, break ahead of the timeout so we make certain
    # to write to the repo
    if time.time() - t0 > (40 * 60):
        break
    $PROJECT = attrs['name']
    $VERSION = attrs['new_version']
    # If there is a new version and (we haven't issued a PR or our prior PR is out of date)
    if not attrs.get('PRed', False) or parse_version(attrs['PRed']) < parse_version(attrs['new_version']):
        print('BUILDING', $PROJECT)
        pred = [(name, gx2.node[name]['new_version'])
                for name in list(gx2.predecessors(node))]
        try:
            # Don't bother running if we are at zero
            if gh.rate_limit()['resources']['core']['remaining'] == 0:
                break
            else:
                run(pred=pred, gh=gh, rerender=True, protocol='https',
                    hash_type=attrs.get('hash_type', 'sha256'))
                gx.nodes[node]['PRed'] = attrs['new_version']
        except github3.GitHubError as e:
            print('GITHUB ERROR ON FEEDSTOCK: {}'.format($PROJECT))
            print(e)
            # carve out for PRs already submitted
            if e.msg == 'Validation Failed':
                gx.nodes[node]['PRed'] = attrs['new_version']
            c = gh.rate_limit()['resources']['core']
            if c['remaining'] == 0:
                ts = c['reset']
                print('API timeout, API returns at')
                print(datetime.datetime.utcfromtimestamp(ts)
                      .strftime('%Y-%m-%dT%H:%M:%SZ'))
                break
        except Exception as e:
            print('NON GITHUB ERROR')
            print(e)
            # print(traceback.format_exc())
            with open('exceptions.txt', 'a') as f:
                f.write('{name}: {exception}'.format(name=$PROJECT, exception=str(e)))
        finally:
            # Write graph partially through
            # Race condition?
            # nx.write_yaml(gx, 'graph.yml')
            nx.write_gpickle(gx, 'graph.pkl')
            rm -rf $REVER_DIR + '/*'
            print(![pwd])
            ![doctr deploy --token --built-docs . --deploy-repo regro/cf-graph --deploy-branch-name master .]

print('API Calls Remaining:', gh.rate_limit()['resources']['core']['remaining'])
print('Done')
