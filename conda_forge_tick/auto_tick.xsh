"""Copyright (c) 2017, Anthony Scopatz"""
import copy
import json
import os
import time
import traceback

import datetime
from doctr.travis import run_command_hiding_token as doctr_run
import github3
import networkx as nx
from rever.tools import indir

from .git_utils import (get_repo, push_repo)
from .path_lengths import cyclic_topological_sort

# TODO: move this back to the bot file as soon as the source issue is sorted
# https://travis-ci.org/regro/00-find-feedstocks/jobs/388387895#L1870
from .migrators import *
$MIGRATORS = [
    Version(pr_limit=0),
    Compiler(pr_limit=0),
    Noarch(pr_limit=1),
]

def run(attrs, migrator, feedstock=None, protocol='ssh',
        pull_request=True, rerender=True, fork=True, gh=None,
        **kwargs):
    """For a given feedstock and migration run the migration

    Parameters
    ----------
    attrs: dict
        The node attributes
    migrator: Migrator instance
        The migrator to run on the feedstock
    feedstock : str, optional
        The feedstock to clone if None use $FEEDSTOCK
    protocol : str, optional
        The git protocol to use, defaults to ``ssh``
    pull_request : bool, optional
        If true issue pull request, defaults to true
    fork : bool
        If true create a fork, defaults to true
    gh : github3.GitHub instance, optional
        Object for communicating with GitHub, if None build from $USERNAME
        and $PASSWORD, defaults to None
    kwargs: dict
        The key word arguments to pass to the migrator

    Returns
    -------
    migrate_return: namedtuple
        The migration return dict used for tracking finished migrations
    pr_json: str
        The PR json object for recreating the PR as needed

    """
    # get the repo
    migrator.attrs = attrs
    feedstock_dir, repo = get_repo(attrs,
                                   branch=migrator.remote_branch(),
                                   feedstock=feedstock,
                                   protocol=protocol,
                                   pull_request=pull_request,
                                   fork=fork,
                                   gh=gh)

    # migrate the `meta.yaml`
    recipe_dir = os.path.join(feedstock_dir, 'recipe')
    migrate_return = migrator.migrate(recipe_dir, attrs, **kwargs)
    if not migrate_return:
        print($PROJECT, attrs.get('bad'))
        rm -rf @(feedstock_dir)
        return False, False

    # rerender, maybe
    with indir(feedstock_dir), ${...}.swap(RAISE_SUBPROC_ERROR=False):
        git commit -am @(migrator.commit_message())
        if rerender:
            print('Rerendering the feedstock')
            conda smithy rerender -c auto

    # push up
    try:
        pr_json = push_repo(feedstock_dir,
                            migrator.pr_body(),
                            repo,
                            migrator.pr_title(),
                            migrator.pr_head(),
                            migrator.remote_branch())

    # This shouldn't happen too often any more since we won't double PR
    except github3.GitHubError as e:
        if e.msg != 'Validation Failed':
            raise
        else:
            # If we just push to the existing PR then do nothing to the json
            pr_json = False

    # If we've gotten this far then the node is good
    attrs['bad'] = False
    print('Removing feedstock dir')
    rm -rf @(feedstock_dir)
    return migrate_return, pr_json


def main(args=None):
    temp = g`/tmp/*`
    gx = nx.read_gpickle('graph.pkl')
    $REVER_DIR = './feedstocks/'
    $REVER_QUIET = True
    gh = github3.login($USERNAME, $PASSWORD)

    smithy_version = ![conda smithy --version].output.strip()
    pinning_version = json.loads(![conda list conda-forge-pinning --json].output.strip())[0]['version']
    good_prs = 0
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

        top_level = set(node for node in gx2 if not list(gx2.predecessors(node)))
        for node in cyclic_topological_sort(gx2, top_level):
            attrs = gx2.nodes[node]
            # Don't let travis timeout, break ahead of the timeout so we make certain
            # to write to the repo
            if time.time() - int($START_TIME) > int($TIMEOUT) or good_prs >= migrator.pr_limit:
                break
            $PROJECT = attrs['feedstock_name']
            $NODE = node
            print('{} IS MIGRATING'.format(migrator.__class__.__name__.upper()),
                  $PROJECT)
            try:
                # Don't bother running if we are at zero
                if gh.rate_limit()['resources']['core']['remaining'] == 0:
                    break
                rerender = (gx.nodes[node].get('smithy_version') != smithy_version or
                            gx.nodes[node].get('pinning_version') != pinning_version or
                            migrator.rerender)
                migrator_uid, pr_json = run(attrs=attrs, migrator=migrator, gh=gh,
                                            rerender=rerender, protocol='https',
                                            hash_type=attrs.get('hash_type', 'sha256'))
                if migrator_uid:
                    gx.nodes[node].setdefault('PRed', []).append(migrator_uid)
                    gx.nodes[node].update({'smithy_version': smithy_version,
                                           'pinning_version': pinning_version})

                # Stash the pr json data so we can access it later
                if pr_json:
                    gx.nodes[node].setdefault('PRed_json', []).append(
                        (migrator_uid, pr_json))

            except github3.GitHubError as e:
                if e.msg == 'Repository was archived so is read-only.':
                    gx.nodes[node]['archived'] = True
                else:
                    print('GITHUB ERROR ON FEEDSTOCK: {}'.format($PROJECT))
                    print(e)
                    print(e.response)

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
                gx.nodes[node]['bad'] = {'exception': str(e),
                                         'traceback': str(traceback.format_exc())}
            else:
                # On successful PR add to our counter
                good_prs += 1
            finally:
                # Write graph partially through
                # Race condition?
                # nx.write_yaml(gx, 'graph.yml')
                nx.write_gpickle(gx, 'graph.pkl')
                rm -rf $REVER_DIR + '/*'
                print(![pwd])
                try:
                    git commit -am @("Migrated {}".format($PROJECT))
                except Exception as e:
                    print(e)
                doctr_run(
                    ['git',
                     'push',
                     'https://{token}@github.com/{deploy_repo}.git'.format(
                         token=$PASSWORD, deploy_repo = 'regro/cf-graph'),
                'master'],
                token=$PASSWORD.encode('utf-8'))
                for f in g`/tmp/*`:
                    if f not in temp:
                        rm -rf @(f)

    print('API Calls Remaining:', gh.rate_limit()['resources']['core']['remaining'])
    print('Done')


if __name__ == "__main__":
    main()
