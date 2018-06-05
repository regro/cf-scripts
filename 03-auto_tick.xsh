"""Copyright (c) 2017, Anthony Scopatz"""
import copy
import json
import os
import time

import datetime
import github3
import networkx as nx
from rever.tools import indir

from conda_forge_tick.git_utils import (get_repo, push_repo)

# TODO: move this back to the bot file as soon as the source issue is sorted
# https://travis-ci.org/regro/00-find-feedstocks/jobs/388387895#L1870
from conda_forge_tick.migrators import *
$MIGRATORS = [Version(), JS()]

def run(attrs, migrator, feedstock=None, protocol='ssh',
        pull_request=True, rerender=True, fork=True, gh=None,
        **kwargs):
    # get the repo
    feedstock_dir = get_repo(feedstock=feedstock, protocol=protocol,
             pull_request=pull_request, fork=fork, gh=gh)

    # migrate the `meta.yaml`
    recipe_dir = os.path.join(feedstock_dir, 'recipe')
    if not migrator.migrate(recipe_dir, attrs, **kwargs):
        rm -rf @ (feedstock_dir)
        return False

    # rerender, maybe
    with indir(feedstock_dir), ${...}.swap(RAISE_SUBPROC_ERROR=False):
        git commit -am @(migrator.commit_message())
        if rerender:
            print('Rerendering the feedstock')
            conda smithy rerender -c auto

    # push up
    push_repo(feedstock_dir, migrator.pr_body())
    # If we've gotten this far then the node is good
    attrs['bad'] = False
    print('Removing feedstock dir')
    rm -rf @(feedstock_dir)
    return True

# gx = nx.read_yaml('graph.yml')
gx = nx.read_gpickle('graph.pkl')
$REVER_DIR = './feedstocks/'
$REVER_QUIET = True
gh = github3.login($USERNAME, $PASSWORD)
t0 = time.time()

smithy_version = ![conda smithy --version].output.strip()
pinning_version = json.loads(![conda list conda-forge-pinning --json].output.strip())[0]['version']
# TODO: need to also capture pinning version, maybe it is in the graph?

for migrator in $MIGRATORS:
    gx2 = copy.deepcopy(gx)

    # Prune graph to only things that need builds
    for node, attrs in gx.node.items():
        if migrator.filter(attrs):
            gx2.remove_node(node)
    $SUBGRAPH = gx2
    print('Total migrations for {}: {}'.format(migrator.__class__.__name__,
                                               len(gx2.node)))

    for node, attrs in gx2.node.items():
        # Don't let travis timeout, break ahead of the timeout so we make certain
        # to write to the repo
        if time.time() - int($START_TIME) > int($TIMEOUT):
            break
        $PROJECT = attrs['feedstock_name']
        $VERSION = attrs['new_version']
        $NODE = node
        print('BOT IS MIGRATING', $PROJECT)
        try:
            # Don't bother running if we are at zero
            if gh.rate_limit()['resources']['core']['remaining'] == 0:
                break
            else:
                if (gx.nodes[node].get('smithy_version') != smithy_version and
                    gx.nodes[node].get('pinning_version') != pinning_version):
                    run(attrs=attrs, migrator=migrator, gh=gh, rerender=True, protocol='https',
                        hash_type=attrs.get('hash_type', 'sha256'))
                else:
                    run(attrs=attrs, migrator=migrator, gh=gh, rerender=False, protocol='https',
                        hash_type=attrs.get('hash_type', 'sha256'))
                # TODO: capture pinning here too!
                gx.nodes[node].update({'PRed': attrs['new_version'],
                                       'smithy_version': smithy_version,
                                       'pinning_version': pinning_version})
        except github3.GitHubError as e:
            print('GITHUB ERROR ON FEEDSTOCK: {}'.format($PROJECT))
            print(e)
            # carve out for PRs already submitted
            if e.msg == 'Validation Failed':
                gx.nodes[node]['PRed'] = attrs['new_version']
            elif e.msg == 'Repository was archived so is read-only.':
                gx.nodes[node]['archived'] = True
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
            with open('exceptions.md', 'a') as f:
                f.write('#{name}\n##{exception}\n{tb}\n\n'.format(
                    name=$PROJECT, exception=str(e),
                    tb=str(traceback.format_exc())))
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
