"""Utilities for managing github repos"""
import datetime
import os
import time
from typing import Optional, Union, Tuple

import github3
import github3.pulls
import github3.repos
import github3.exceptions
import github3.repos

from doctr.travis import run_command_hiding_token as doctr_run
from .xonsh_utils import env, indir

import backoff

backoff._decorator._is_event_loop = lambda: False

from requests.exceptions import Timeout, RequestException
from .contexts import GithubContext, FeedstockContext, MigratorsContext

MAX_GITHUB_TIMEOUT = 60

# TODO: handle the URLs more elegantly (most likely make this a true library
# and pull all the needed info from the various source classes)
from conda_forge_tick.utils import LazyJson


def ensure_gh(ctx: GithubContext, gh: Optional[github3.Github]) -> github3.GitHub:
    if gh is None:
        gh = github3.login(ctx.github_username, ctx.github_password)
    return gh


def feedstock_url(
    fctx: FeedstockContext, feedstock: Optional[str], protocol: str = "ssh",
) -> str:
    """Returns the URL for a conda-forge feedstock."""
    if feedstock is None:
        feedstock = fctx.package_name + "-feedstock"
    elif feedstock.startswith("http://github.com/"):
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


def feedstock_repo(fctx: FeedstockContext, feedstock: Optional[str]) -> str:
    """Gets the name of the feedstock repository."""
    if feedstock is None:
        repo = fctx.package_name + "-feedstock"
    else:
        repo = feedstock
    repo = repo.rsplit("/", 1)[-1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return repo


def fork_url(feedstock_url: str, username: str) -> str:
    """Creates the URL of the user's fork."""
    beg, end = feedstock_url.rsplit("/", 1)
    beg = beg[:-11]  # chop off 'conda-forge'
    url = beg + username + "/" + end
    return url


def get_repo(
    ctx: MigratorsContext,
    fctx: FeedstockContext,
    branch: str,
    feedstock: Optional[str] = None,
    protocol: str = "ssh",
    pull_request: bool = True,
    fork: bool = True,
) -> Tuple[str, github3.repos.Repository]:
    """Get the feedstock repo

    Parameters
    ----------
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
    gh = ctx.gh
    # first, let's grab the feedstock locally
    upstream = feedstock_url(fctx=fctx, feedstock=feedstock, protocol=protocol)
    origin = fork_url(upstream, ctx.github_username)
    feedstock_reponame = feedstock_repo(fctx=fctx, feedstock=feedstock)

    if pull_request or fork:
        repo = gh.repository("conda-forge", feedstock_reponame)
        if repo is None:
            fctx.attrs["bad"] = "{}: does not match feedstock name\n".format(
                fctx.package_name,
            )
            return False

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
    from conda_forge_tick.git_xonsh_utils import fetch_repo

    if fetch_repo(
        feedstock_dir=feedstock_dir, origin=origin, upstream=upstream, branch=branch,
    ):
        return feedstock_dir, repo
    else:
        return None


def delete_branch(ctx: GithubContext, pr_json: LazyJson, dry_run: bool = False) -> None:
    ref = pr_json["head"]["ref"]
    if dry_run:
        print("dry run: deleting ref %s" % ref)
        return
    name = pr_json["base"]["repo"]["name"]
    token = ctx.github_password
    deploy_repo = ctx.github_username + "/" + name
    doctr_run(
        [
            "git",
            "push",
            "https://{token}@github.com/{deploy_repo}.git".format(
                token=token, deploy_repo=deploy_repo,
            ),
            "--delete",
            ref,
        ],
        token=token.encode("utf-8"),
    )
    # Replace ref so we know not to try again
    pr_json["head"]["ref"] = "this_is_not_a_branch"


@backoff.on_exception(
    backoff.expo, (RequestException, Timeout), max_time=MAX_GITHUB_TIMEOUT,
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
            print("dry run: refresh pr %s" % dict(pr_json))
        else:
            pr_obj = github3.pulls.PullRequest(dict(pr_json), gh)
            pr_obj.refresh(True)
            pr_obj_d = pr_obj.as_dict()
            # if state passed from opened to merged or if it
            # closed for a day delete the branch
            if pr_obj_d["state"] == "closed" and pr_obj_d.get("merged_at", False):
                delete_branch(ctx=ctx, pr_json=pr_json, dry_run=dry_run)
        return pr_obj.as_dict()
    return None


@backoff.on_exception(
    backoff.expo, (RequestException, Timeout), max_time=MAX_GITHUB_TIMEOUT,
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
        l["name"] for l in pr_json["labels"]
    ]:
        # update
        if dry_run:
            print("dry run: checking pr %s" % dict(pr_json))
        else:
            pr_obj = github3.pulls.PullRequest(dict(pr_json), gh)
            pr_obj.refresh(True)
            pr_json = pr_obj.as_dict()

    if pr_json["state"] != "closed" and "bot-rerun" in [
        l["name"] for l in pr_json["labels"]
    ]:
        if dry_run:
            print("dry run: comment and close pr %s" % dict(pr_json))
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
    ctx: MigratorsContext,
    fctx: FeedstockContext,
    feedstock_dir: str,
    body: str,
    repo: github3.repos.Repository,
    title: str,
    head: str,
    branch: str,
    pull_request: bool = True,
) -> Union[LazyJson, bool, None]:
    """Push a repo up to github

    Parameters
    ----------
    feedstock_dir : str
        The feedstock directory
    body : str
        The PR body
    dry_run : bool, optional
        If True, does not interact with git

    Returns
    -------
    pr_json: str
        The json object representing the PR, can be used with `from_json`
        to create a PR instance.
    """
    with indir(feedstock_dir), env.swap(RAISE_SUBPROC_ERROR=False):
        # Setup push from doctr
        # Copyright (c) 2016 Aaron Meurer, Gil Forsyth
        token = ctx.github_password
        deploy_repo = ctx.github_username + "/" + fctx.feedstock_name + "-feedstock"
        if ctx.dry_run:
            repo_url = "https://github.com/{deploy_repo}.git".format(
                deploy_repo=deploy_repo,
            )
            print("dry run: adding remote and pushing up branch for %s" % repo_url)
        else:
            doctr_run(
                [
                    "git",
                    "remote",
                    "add",
                    "regro_remote",
                    "https://{token}@github.com/{deploy_repo}.git".format(
                        token=token, deploy_repo=deploy_repo,
                    ),
                ],
                token=token.encode("utf-8"),
            )

            doctr_run(
                ["git", "push", "--set-upstream", "regro_remote", branch],
                token=token.encode("utf-8"),
            )
    # lastly make a PR for the feedstock
    print("Creating conda-forge feedstock pull request...")
    if ctx.dry_run:
        print("dry run: create pr with title: %s" % title)
        return False
    else:
        pr = repo.create_pull(title, "master", head, body=body)
        if pr is None:
            print("Failed to create pull request!")
            return False
        else:
            print("Pull request created at " + pr.html_url)
    # Return a json object so we can remake the PR if needed
    pr_dict = pr.as_dict()
    ljpr = LazyJson(os.path.join(ctx.prjson_dir, str(pr_dict["id"]) + ".json"))
    ljpr.update(**pr_dict)
    return ljpr


@backoff.on_exception(
    backoff.expo, (RequestException, Timeout), max_time=MAX_GITHUB_TIMEOUT,
)
def ensure_label_exists(
    repo: github3.repos.Repository, label_dict: dict, dry_run: bool = False,
) -> None:
    if dry_run:
        print("dry run: ensure label exists %s" % label_dict["name"])
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
        print(
            "dry run: label pr {} with {}".format(
                pr_json["number"], label_dict["name"],
            ),
        )
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
