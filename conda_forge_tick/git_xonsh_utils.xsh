import os
import sys
from subprocess import CalledProcessError

from xonsh.lib.os import indir


def fetch_repo(*, feedstock_dir, origin, upstream, branch, base_branch="master") -> bool:
    if not os.path.isdir(feedstock_dir):
        p = ![git clone -q @(origin) @(feedstock_dir)]
        if p.rtn != 0:
            msg = 'Could not clone ' + origin
            msg += '. Do you have a personal fork of the feedstock?'
            print(msg, file=sys.stderr)
            return False
    with indir(feedstock_dir):
        git fetch @(origin) --quiet
        # make sure feedstock is up-to-date with origin
        git checkout @(base_branch)
        git pull @(origin) @(base_branch) --quiet
        # remove any uncommitted changes?
        git reset --hard HEAD
        # make sure feedstock is up-to-date with upstream
        # git pull @(upstream) @(base_branch) -s recursive -X theirs --no-edit

        # doesn't work if the upstream already exists
        try:
            # always run upstream
            git remote add upstream @(upstream)
        except CalledProcessError:
            pass
        git fetch upstream @(base_branch) --quiet
        git reset --hard upstream/@(base_branch)
        # make and modify version branch
        with ${...}.swap(RAISE_SUBPROC_ERROR=False):
            git checkout @(branch) --quiet or git checkout -b @(branch) @(base_branch) --quiet
    return True
