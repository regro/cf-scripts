"""Utilities for managing github repos"""
import copy
import datetime
import os
import time
import traceback
import urllib.error
import json
from tempfile import TemporaryDirectory

import github3
import github3.pulls

import networkx as nx
import requests
from doctr.travis import run_command_hiding_token as doctr_run
from pkg_resources import parse_version
from rever.tools import (eval_version, hash_url, replace_in_file)
from xonsh.lib.os import indir


# TODO: handle the URLs more elegantly (most likely make this a true library
# and pull all the needed info from the various source classes)
from conda_forge_tick.utils import LazyJson


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


def get_repo(attrs, branch, feedstock=None, protocol='ssh',
             pull_request=True, fork=True, gh=None):
    """Get the feedstock repo

    Parameters
    ----------
    attrs : dict
        The node attributes
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

    Returns
    -------
    recipe_dir : str
        The recipe directory
    """
    if gh is None:
        gh = github3.login($USERNAME, $PASSWORD)
    # first, let's grab the feedstock locally
    upstream = feedstock_url(feedstock, protocol=protocol)
    origin = fork_url(upstream, $USERNAME)
    feedstock_reponame = feedstock_repo(feedstock)

    if pull_request or fork:
        repo = gh.repository('conda-forge', feedstock_reponame)
        if repo is None:
            attrs['bad'] = '{}: does not match feedstock name\n'.format($PROJECT)
            return False

    # Check if fork exists
    if fork:
        try:
            fork_repo = gh.repository($USERNAME, feedstock_reponame)
        except github3.GitHubError:
            fork_repo = None
        if fork_repo is None or (hasattr(fork_repo, 'is_null') and
                                 fork_repo.is_null()):
            print("Fork doesn't exist creating feedstock fork...")
            repo.create_fork()
            # Sleep to make sure the fork is created before we go after it
            time.sleep(5)

    feedstock_dir = os.path.join($REVER_DIR, $PROJECT + '-feedstock')
    if not os.path.isdir(feedstock_dir):
        p = ![git clone -q @(origin) @(feedstock_dir)]
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
            git checkout @(branch) or git checkout -b @(branch) master
    return feedstock_dir, repo


def delete_branch(pr_json: LazyJson):
    ref = pr_json['head']['ref']
    name = pr_json['base']['repo']['name']
    token = $PASSWORD
    deploy_repo = $USERNAME + '/' + name
    doctr_run(['git', 'push', 'https://{token}@github.com/{deploy_repo}.git'.format(
                   token=token, deploy_repo=deploy_repo), '--delete', ref],
              token=token.encode('utf-8'))


def refresh_pr(pr_json: LazyJson, gh=None):
    if gh is None:
        gh = github3.login($USERNAME, $PASSWORD)
    if not pr_json['state'] == 'closed':
        pr_obj = github3.pulls.PullRequest(pr_json, gh)
        pr_obj.refresh()
        pr_obj_d = pr_obj.as_dict()
        # if state passed from opened to closed delete the branch
        if pr_obj_d['state'] == 'closed' and pr_obj_d.get('merged_at', False):
            delete_branch(pr_json)
        return pr_obj.as_dict()


def ping_maintainers(pr_json: LazyJson, gh=None):
    if gh is None:
        gh = github3.login($USERNAME, $PASSWORD)
    if not pr_json['state'] == 'closed':
        r = requests.get(pr_json['statuses_url'],
                         auth=($USERNAME, $PASSWORD))
        if r.status_code != 200:
            return dict(pr_json)
        statuses_json = r.json()
        current_status = {i['context']: (i['state'], i['id']) for i in
             sorted(statuses_json, key=lambda x: x['updated_at'])}
        cached_status = LazyJson(
            os.path.join('pr_status', '{}_status.json'.format(pr_json['id'] )))
        # If the status has been updated, and none are pending
        if current_status != cached_status and all(i[0] != 'pending' for i in current_status.values()):
            pr_obj = github3.pulls.PullRequest(pr_json, gh)
            if pr_obj.create_comment('''Hi @{}, I think all the CI statuses have
            come in. This PR is ready for review/merge'''.format('conda-forge/' + pr_json['head']['repo']['name'])):
                cached_status.update(**current_status)
            return pr_obj.as_dict()
        return pr_json


def close_out_labels(pr_json: LazyJson, gh=None):
    if gh is None:
        gh = github3.login($USERNAME, $PASSWORD)
    if pr_json['state'] != 'closed' and 'bot-rerun' in [l['name'] for l in pr_json['labels']]:
        pr_obj = github3.pulls.PullRequest(pr_json, gh)
        pr_obj.create_comment("Due to the `bot-rerun` label I'm closing "
                              "this PR. I will make another one as"
                              " appropriate.")
        pr_obj.close()
        delete_branch(pr_json)
        return pr_obj.as_dict()


def push_repo(feedstock_dir, body, repo, title, head, branch,
              pull_request=True):
    """Push a repo up to github

    Parameters
    ----------
    feedstock_dir : str
        The feedstock directory
    body : str
        The PR body
    pull_request : bool, optional
        If True issue pull request, defaults to True

    Returns
    -------
    pr_json: str
        The json object representing the PR, can be used with `from_json`
        to create a PR instance.
    """
    with indir(feedstock_dir), ${...}.swap(RAISE_SUBPROC_ERROR=False):
        # Setup push from doctr
        # Copyright (c) 2016 Aaron Meurer, Gil Forsyth
        token = $PASSWORD
        deploy_repo = $USERNAME + '/' + $PROJECT + '-feedstock'
        doctr_run(['git', 'remote', 'add', 'regro_remote',
                   'https://{token}@github.com/{deploy_repo}.git'.format(
                       token=token, deploy_repo=deploy_repo)],
                  token=token.encode('utf-8'))

        doctr_run(['git', 'push', '--set-upstream', 'regro_remote', branch],
                  token=token.encode('utf-8'))
    # lastly make a PR for the feedstock
    if not pull_request:
        return
    print('Creating conda-forge feedstock pull request...')
    pr = repo.create_pull(title, 'master', head, body=body)
    if pr is None:
        print('Failed to create pull request!')
    else:
        print('Pull request created at ' + pr.html_url)
    # Return a json object so we can remake the PR if needed
    pr_dict = pr.as_dict()
    ljpr = LazyJson(os.path.join($PRJSON_DIR, str(pr_dict['id']) + '.json'))
    ljpr.update(**pr_dict)
    return ljpr


def is_github_api_limit_reached(e: github3.GitHubError, gh: github3.GitHub) -> bool:
    """Prints diagnostic information about a github exception.

    Returns
    -------
    out_of_api_credits
        A flag to indicate that the api limit has been exhausted
    """
    print(e)
    print(e.response)
    print(e.response.url)
    if 'Retry-After' in e.response.headers:
        print('Retry-After {}'.format(e.response.headers['Retry-After']))

    c = gh.rate_limit()['resources']['core']
    if c['remaining'] == 0:
        ts = c['reset']
        print('API timeout, API returns at')
        print(datetime.datetime.utcfromtimestamp(ts)
              .strftime('%Y-%m-%dT%H:%M:%SZ'))
        return True
    return False
