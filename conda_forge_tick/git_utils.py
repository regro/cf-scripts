"""Utilities for managing github repos"""
import datetime
import os
import time
import sys
from typing import Optional, Union, Tuple
import subprocess

import github3
import github3.pulls
import github3.repos
import github3.exceptions
import github3.repos

from doctr.travis import run_command_hiding_token as doctr_run
from .xonsh_utils import env, indir

from requests.exceptions import Timeout, RequestException
from .contexts import GithubContext, FeedstockContext, MigratorSessionContext

import backoff

# TODO: handle the URLs more elegantly (most likely make this a true library
# and pull all the needed info from the various source classes)
from conda_forge_tick.utils import LazyJson

backoff._decorator._is_event_loop = lambda: False

MAX_GITHUB_TIMEOUT = 60

DUMMY_BOT_RERUN_METADATA = {
    "color": "191970",
    "default": False,
    "description": "Instruct the bot to retry the PR",
    "id": 1,
    "name": "bot-rerun",
    "node_id": "hello",
    "url": "world",
}

CF_BOT_NAMES = {"regro-cf-autotick-bot", "conda-forge-linter"}


def ensure_gh(ctx: GithubContext, gh: Optional[github3.GitHub]) -> github3.GitHub:
    if gh is None:
        gh = github3.login(ctx.github_username, ctx.github_password)
    return gh


def feedstock_url(fctx: FeedstockContext, protocol: str = "ssh") -> str:
    """Returns the URL for a conda-forge feedstock."""
    feedstock = fctx.feedstock_name + "-feedstock"
    if feedstock.startswith("http://github.com/"):
        return feedstock
    elif feedstock.startswith("https://github.com/"):
        return feedstock
    elif feedstock.startswith("git@github.com:"):
        return feedstock
    protocol = protocol.lower()
    if protocol == "http":
        url = "http://github.com/conda-forge/" + feedstock + ".git"
    elif protocol == "https":
        url = "https://github.com/conda-forge/" + feedstock + ".git"
    elif protocol == "ssh":
        url = "git@github.com:conda-forge/" + feedstock + ".git"
    else:
        msg = "Unrecognized github protocol {0!r}, must be ssh, http, or https."
        raise ValueError(msg.format(protocol))
    return url


def feedstock_repo(fctx: FeedstockContext) -> str:
    """Gets the name of the feedstock repository."""
    repo = fctx.feedstock_name + "-feedstock"
    if repo.endswith(".git"):
        repo = repo[:-4]
    return repo


def fork_url(feedstock_url: str, username: str) -> str:
    """Creates the URL of the user's fork."""
    beg, end = feedstock_url.rsplit("/", 1)
    beg = beg[:-11]  # chop off 'conda-forge'
    url = beg + username + "/" + end
    return url


def fetch_repo(*, feedstock_dir, origin, upstream, branch, base_branch="master"):
    """fetch a repo and make a PR branch

    Parameters
    ----------
    feedstock_dir : str
        The directory where you want to clone the feedstock.
    origin : str
        The origin to clone from.
    upstream : str
        The upstream repo to add as a remote named `upstream`.
    branch : str
        The branch to make and checkout.
    base_branch : str, optional
        The branch from which to branch from to make `branch`. Defaults to "master".

    Returns
    -------
    success : bool
        True if the fetch worked, False otherwise.
    """
    if not os.path.isdir(feedstock_dir):
        p = subprocess.run(
            f"git clone -q {origin} {feedstock_dir}",
            shell=True,
        )
        if p.returncode != 0:
            msg = "Could not clone " + origin
            msg += ". Do you have a personal fork of the feedstock?"
            print(msg, file=sys.stderr)
            return False

    def _run_git_cmd(cmd):
        return subprocess.run(cmd, shell=True, check=True)

    with indir(feedstock_dir):
        # fetch remote changes
        _run_git_cmd(f"git fetch {origin} --quiet")

        # make sure feedstock is up-to-date with upstream
        # doesn't work if the upstream already exists
        try:
            # always run upstream
            _run_git_cmd(f"git remote add upstream {upstream}")
        except subprocess.CalledProcessError:
            pass

        _run_git_cmd(f"git fetch {upstream} {base_branch} --quiet")
        try:
            _run_git_cmd(f"git checkout {base_branch} --quiet")
        except subprocess.CalledProcessError:
            _run_git_cmd(
                f"git checkout -b {base_branch} upstream/{base_branch} --quiet",
            )
        _run_git_cmd(f"git pull {upstream} {base_branch} --quiet")

        # remove any uncommitted changes?
        _run_git_cmd("git reset --hard HEAD")

        # make and modify version branch
        try:
            _run_git_cmd(f"git checkout {branch} --quiet")
        except subprocess.CalledProcessError:
            _run_git_cmd(f"git checkout -b {branch} {base_branch} --quiet")

    return True


def get_repo(
    ctx: MigratorSessionContext,
    fctx: FeedstockContext,
    branch: str,
    feedstock: Optional[str] = None,
    protocol: str = "ssh",
    pull_request: bool = True,
    fork: bool = True,
    base_branch: str = "master",
) -> Tuple[str, github3.repos.Repository]:
    """Get the feedstock repo

    Parameters
    ----------
    ctx : MigratorSessionContext
        Migrator context. Used to access the github3 object and other github
        information.
    fcts : FeedstockContext
        Feedstock context used for constructing feedstock urls, etc.
    branch : str
        The branch to be made.
    feedstock : str, optional
        The feedstock to clone if None use $FEEDSTOCK
    protocol : str, optional
        The git protocol to use, defaults to ``ssh``
    pull_request : bool, optional
        If true issue pull request, defaults to true
    fork : bool
        If true create a fork, defaults to true
    base_branch : str, optional
        The base branch from which to make the new branch.

    Returns
    -------
    recipe_dir : str
        The recipe directory
    repo : github3 repository
        The github3 repository object.
    """
    gh = ctx.gh
    # first, let's grab the feedstock locally
    upstream = feedstock_url(fctx=fctx, protocol=protocol)
    origin = fork_url(upstream, ctx.github_username)
    feedstock_reponame = feedstock_repo(fctx=fctx)

    if pull_request or fork:
        repo = gh.repository("conda-forge", feedstock_reponame)
        if repo is None:
            print("could not fork conda-forge/%s!" % feedstock_reponame, flush=True)
            fctx.attrs["bad"] = f"{fctx.package_name}: does not match feedstock name\n"
            return False, False

    # Check if fork exists
    if fork:
        try:
            fork_repo = gh.repository(ctx.github_username, feedstock_reponame)
        except github3.GitHubError:
            fork_repo = None
        if fork_repo is None or (hasattr(fork_repo, "is_null") and fork_repo.is_null()):
            print("Fork doesn't exist creating feedstock fork...")
            repo.create_fork()
            # Sleep to make sure the fork is created before we go after it
            time.sleep(5)

    feedstock_dir = os.path.join(ctx.rever_dir, fctx.package_name + "-feedstock")

    if fetch_repo(
        feedstock_dir=feedstock_dir,
        origin=origin,
        upstream=upstream,
        branch=branch,
        base_branch=base_branch,
    ):
        return feedstock_dir, repo
    else:
        return False, False


def delete_branch(ctx: GithubContext, pr_json: LazyJson, dry_run: bool = False) -> None:
    ref = pr_json["head"]["ref"]
    if dry_run:
        print(f"dry run: deleting ref {ref}")
        return
    name = pr_json["base"]["repo"]["name"]
    token = ctx.github_password
    deploy_repo = ctx.github_username + "/" + name
    doctr_run(
        [
            "git",
            "push",
            f"https://{token}@github.com/{deploy_repo}.git",
            "--delete",
            ref,
        ],
        token=token.encode("utf-8"),
    )
    # Replace ref so we know not to try again
    pr_json["head"]["ref"] = "this_is_not_a_branch"


@backoff.on_exception(
    backoff.expo,
    (RequestException, Timeout),
    max_time=MAX_GITHUB_TIMEOUT,
)
def refresh_pr(
    ctx: GithubContext,
    pr_json: LazyJson,
    gh: Optional[github3.GitHub] = None,
    dry_run: bool = False,
) -> Optional[dict]:
    gh = ensure_gh(ctx, gh)
    if not pr_json["state"] == "closed":
        if dry_run:
            print("dry run: refresh pr %s" % pr_json["id"])
            pr_dict = dict(pr_json)
        else:
            pr_obj = github3.pulls.PullRequest(dict(pr_json), gh)
            pr_obj.refresh(True)
            pr_obj_d = pr_obj.as_dict()
            # if state passed from opened to merged or if it
            # closed for a day delete the branch
            if pr_obj_d["state"] == "closed" and pr_obj_d.get("merged_at", False):
                delete_branch(ctx=ctx, pr_json=pr_json, dry_run=dry_run)
            pr_dict = pr_obj.as_dict()
        return pr_dict
    return None


@backoff.on_exception(
    backoff.expo,
    (RequestException, Timeout),
    max_time=MAX_GITHUB_TIMEOUT,
)
def close_out_labels(
    ctx: GithubContext,
    pr_json: LazyJson,
    gh: Optional[github3.GitHub] = None,
    dry_run: bool = False,
) -> Optional[dict]:
    gh = ensure_gh(ctx, gh)
    # run this twice so we always have the latest info (eg a thing was already closed)
    if pr_json["state"] != "closed" and "bot-rerun" in [
        lab["name"] for lab in pr_json.get("labels", [])
    ]:
        # update
        if dry_run:
            print("dry run: checking pr %s" % pr_json["id"])
        else:
            pr_obj = github3.pulls.PullRequest(dict(pr_json), gh)
            pr_obj.refresh(True)
            pr_json = pr_obj.as_dict()

    if pr_json["state"] != "closed" and "bot-rerun" in [
        lab["name"] for lab in pr_json.get("labels", [])
    ]:
        if dry_run:
            print("dry run: comment and close pr %s" % pr_json["id"])
        else:
            pr_obj.create_comment(
                "Due to the `bot-rerun` label I'm closing "
                "this PR. I will make another one as"
                " appropriate. This was generated by {}".format(ctx.circle_build_url),
            )
            pr_obj.close()
            delete_branch(ctx=ctx, pr_json=pr_json, dry_run=dry_run)
            pr_obj.refresh(True)
        return pr_obj.as_dict()
    return None


def push_repo(
    session_ctx: MigratorSessionContext,
    fctx: FeedstockContext,
    feedstock_dir: str,
    body: str,
    repo: github3.repos.Repository,
    title: str,
    head: str,
    branch: str,
    base_branch: str = "master",
) -> Union[dict, bool, None]:
    """Push a repo up to github

    Parameters
    ----------
    ctx : MigratorSessionContext
        Migrator context. Used to access the github3 object and other github
        information.
    fcts : FeedstockContext
        Feedstock context used for constructing feedstock urls, etc.
    feedstock_dir : str
        The feedstock directory
    body : str
        The PR body.
    repo : github3.repos.Repository
        The feedstock repo as a github3 object.
    title : str
        The title of the PR.
    head : str
        The github head for the PR in the form `username:branch`.
    branch : str
        The head branch of the PR.
    base_branch : str, optional
        The base branch or target branch of the PR.

    Returns
    -------
    pr_json: dict
        The dict representing the PR, can be used with `from_json`
        to create a PR instance.
    """
    with indir(feedstock_dir), env.swap(RAISE_SUBPROC_ERROR=False):
        # Setup push from doctr
        # Copyright (c) 2016 Aaron Meurer, Gil Forsyth
        token = session_ctx.github_password
        deploy_repo = (
            session_ctx.github_username + "/" + fctx.feedstock_name + "-feedstock"
        )
        if session_ctx.dry_run:
            repo_url = f"https://github.com/{deploy_repo}.git"
            print(f"dry run: adding remote and pushing up branch for {repo_url}")
        else:
            doctr_run(
                [
                    "git",
                    "remote",
                    "add",
                    "regro_remote",
                    f"https://{token}@github.com/{deploy_repo}.git",
                ],
                token=token.encode("utf-8"),
            )

            doctr_run(
                ["git", "push", "--set-upstream", "regro_remote", branch],
                token=token.encode("utf-8"),
            )
    # lastly make a PR for the feedstock
    print("Creating conda-forge feedstock pull request...")
    if session_ctx.dry_run:
        print(f"dry run: create pr with title: {title}")
        return False
    else:
        pr = repo.create_pull(title, base_branch, head, body=body)
        if pr is None:
            print("Failed to create pull request!")
            return False
        else:
            print("Pull request created at " + pr.html_url)
    # Return a json object so we can remake the PR if needed
    pr_dict: dict = pr.as_dict()
    return pr_dict


@backoff.on_exception(
    backoff.expo,
    (RequestException, Timeout),
    max_time=MAX_GITHUB_TIMEOUT,
)
def ensure_label_exists(
    repo: github3.repos.Repository,
    label_dict: dict,
    dry_run: bool = False,
) -> None:
    if dry_run:
        print(f"dry run: ensure label exists {label_dict['name']}")
    try:
        repo.label(label_dict["name"])
    except github3.exceptions.NotFoundError:
        repo.create_label(**label_dict)


def label_pr(
    repo: github3.repos.Repository,
    pr_json: LazyJson,
    label_dict: dict,
    dry_run: bool = False,
) -> None:
    ensure_label_exists(repo, label_dict, dry_run)
    if dry_run:
        print(f"dry run: label pr {pr_json['number']} with {label_dict['name']}")
    else:
        iss = repo.issue(pr_json["number"])
        iss.add_labels(label_dict["name"])


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

    try:
        c = gh.rate_limit()["resources"]["core"]
    except Exception:
        # if we can't connect to the rate limit API, let's assume it has been reached
        return True
    if c["remaining"] == 0:
        ts = c["reset"]
        print("API timeout, API returns at")
        print(datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ"))
        return True
    return False


def close_out_dirty_prs(
    ctx: GithubContext,
    pr_json: LazyJson,
    gh: Optional[github3.GitHub] = None,
    dry_run: bool = False,
) -> Optional[dict]:
    gh = ensure_gh(ctx, gh)
    # run this twice so we always have the latest info (eg a thing was already closed)
    if pr_json["state"] != "closed" and pr_json["mergeable_state"] == "dirty":
        # update
        if dry_run:
            print("dry run: checking pr %s" % pr_json["id"])
        else:
            pr_obj = github3.pulls.PullRequest(dict(pr_json), gh)
            pr_obj.refresh(True)
            pr_json = pr_obj.as_dict()

    if pr_json["state"] != "closed" and pr_json["mergeable_state"] == "dirty":
        d = pr_obj.as_dict()
        if dry_run:
            print("dry run: comment and close pr %s" % pr_json["id"])
        else:
            if all(
                c.as_dict()["commit"]["author"]["name"] in CF_BOT_NAMES
                for c in pr_obj.commits()
            ):
                pr_obj.create_comment(
                    "I see that this PR has conflicts and I'm the only committer "
                    "I'm going to close this PR and will make another one as"
                    " appropriate. This was generated by {}".format(
                        ctx.circle_build_url,
                    ),
                )
                pr_obj.close()
                delete_branch(ctx=ctx, pr_json=pr_json, dry_run=dry_run)
                pr_obj.refresh(True)
                d = pr_obj.as_dict()
                # This will cause the update_nodes_with_bot_rerun to trigger
                # properly and shouldn't be overridden since
                # this is the last function to run, the long term solution here
                # is to add the bot to conda-forge and then
                # it should have label adding capability and we can just add
                # the label properly
                d["labels"].append(DUMMY_BOT_RERUN_METADATA)
            else:
                d = pr_obj.as_dict()
        return d
    return None
