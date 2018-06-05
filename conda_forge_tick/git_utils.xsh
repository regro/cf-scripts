"""Utilities for managing github repos"""
import copy
import datetime
import os
import time
import traceback
import urllib.error

import github3
import networkx as nx
from doctr.travis import run as doctr_run
from pkg_resources import parse_version
from rever.tools import (eval_version, indir, hash_url, replace_in_file)

from conda_forge_tick.utils import parsed_meta_yaml

# TODO: handle the URLs more elegantly (most likely make this a true library
# and pull all the needed info from the various source classes)
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


def get_repo(attrs, feedstock=None, protocol='ssh',
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
        fork_repo = gh.repository($USERNAME, feedstock_reponame)
        if fork_repo is None or (hasattr(fork_repo, 'is_null') and
                                 fork_repo.is_null()):
            print("Fork doesn't exist creating feedstock fork...")
            repo.create_fork()
            # Sleep to make sure the fork is created before we go after it
            time.sleep(5)

    feedstock_dir = os.path.join($REVER_DIR, $PROJECT + '-feedstock')
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
    return feedstock_dir


def push_repo(feedstock_dir, body):
    """Push a repo up to github

    Parameters
    ----------
    feedstock_dir : str
        The feedstock directory
    body : str
        The PR body
    """
    with indir(feedstock_dir), ${...}.swap(RAISE_SUBPROC_ERROR=False):
        # Setup push from doctr
        # Copyright (c) 2016 Aaron Meurer, Gil Forsyth
        token = $PASSWORD
        deploy_repo = $USERNAME + '/' + $PROJECT + '-feedstock'
        doctr_run(['git', 'remote', 'add', 'regro_remote',
                   'https://{token}@github.com/{deploy_repo}.git'.format(
                       token=token, deploy_repo=deploy_repo)])

        git push --set-upstream regro_remote $VERSION
    # lastly make a PR for the feedstock
    if not pull_request:
        return
    print('Creating conda-forge feedstock pull request...')
    title = $PROJECT + ' v' + $VERSION
    head = $USERNAME + ':' + $VERSION
    pr = repo.create_pull(title, 'master', head, body=body)
    if pr is None:
        print('Failed to create pull request!')
    else:
        print('Pull request created at ' + pr.html_url)
