import gc
import glob
import json
import logging
import os
import random
import time
import traceback
import typing
from subprocess import CalledProcessError
from textwrap import dedent
from typing import Literal, MutableMapping, cast
from urllib.error import URLError
from uuid import uuid4

import github
import github3
import networkx as nx
import tqdm
from conda.models.version import VersionOrder

from conda_forge_tick.cli_context import CliContext
from conda_forge_tick.contexts import (
    ClonedFeedstockContext,
    FeedstockContext,
    MigratorSessionContext,
)
from conda_forge_tick.deploy import deploy
from conda_forge_tick.feedstock_parser import BOOTSTRAP_MAPPINGS
from conda_forge_tick.git_utils import (
    comment_on_pr,
    get_repo,
    github_backend,
    is_github_api_limit_reached,
    push_repo,
)
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    get_all_keys_for_hashmap,
    lazy_json_transaction,
    remove_key_for_hashmap,
)
from conda_forge_tick.make_migrators import (
    MAX_SOLVER_ATTEMPTS,
    PR_LIMIT,
    load_migrators,
)
from conda_forge_tick.migration_runner import run_migration
from conda_forge_tick.migrators import MigrationYaml, Migrator, Version
from conda_forge_tick.migrators.version import VersionMigrationError
from conda_forge_tick.os_utils import eval_cmd, pushd
from conda_forge_tick.rerender_feedstock import rerender_feedstock
from conda_forge_tick.solver_checks import is_recipe_solvable
from conda_forge_tick.utils import (
    ContainerRuntimeError,
    change_log_level,
    dump_graph,
    filter_reprinted_lines,
    fold_log_lines,
    frozen_to_json_friendly,
    get_bot_run_url,
    get_keys_default,
    get_migrator_name,
    load_existing_graph,
    sanitize_string,
)

from .migrators_types import MigrationUidTypedDict

logger = logging.getLogger(__name__)

BOT_HOME_DIR: str = os.getcwd()
START_TIME = None
TIMEOUT = int(os.environ.get("TIMEOUT", 600))

# migrator runs on loop so avoid any seeds at current time should that happen
random.seed(os.urandom(64))


def _set_pre_pr_migrator_error(attrs, migrator_name, error_str, *, is_version):
    if is_version:
        with attrs["version_pr_info"] as vpri:
            version = vpri["new_version"]
            if "new_version_errors" not in vpri:
                vpri["new_version_errors"] = {}
            vpri["new_version_errors"][version] = sanitize_string(error_str)
    else:
        pre_key = "pre_pr_migrator_status"

        with attrs["pr_info"] as pri:
            if pre_key not in pri:
                pri[pre_key] = {}
            pri[pre_key][migrator_name] = sanitize_string(
                error_str,
            )


def _increment_pre_pr_migrator_attempt(attrs, migrator_name, *, is_version):
    if is_version:
        with attrs["version_pr_info"] as vpri:
            version = vpri["new_version"]
            if "new_version_attempts" not in vpri:
                vpri["new_version_attempts"] = {}
            if version not in vpri["new_version_attempts"]:
                vpri["new_version_attempts"][version] = 0
            vpri["new_version_attempts"][version] += 1
    else:
        pre_key_att = "pre_pr_migrator_attempts"

        with attrs["pr_info"] as pri:
            if pre_key_att not in pri:
                pri[pre_key_att] = {}
            if migrator_name not in pri[pre_key_att]:
                pri[pre_key_att][migrator_name] = 0
            pri[pre_key_att][migrator_name] += 1


def _reset_pre_pr_migrator_fields(attrs, migrator_name, *, is_version):
    if is_version:
        with attrs["version_pr_info"] as vpri:
            version = vpri["new_version"]
            for _key in ["new_version_errors", "new_version_attempts"]:
                if _key in vpri and version in vpri[_key]:
                    vpri[_key].pop(version)
    else:
        pre_key = "pre_pr_migrator_status"
        pre_key_att = "pre_pr_migrator_attempts"
        with attrs["pr_info"] as pri:
            for _key in [pre_key, pre_key_att]:
                if _key in pri and migrator_name in pri[_key]:
                    pri[_key].pop(migrator_name)


def _get_pre_pr_migrator_attempts(attrs, migrator_name, *, is_version):
    if is_version:
        with attrs["version_pr_info"] as vpri:
            return vpri.get("new_version_attempts", {}).get(vpri["new_version"], 0)
    else:
        with attrs["pr_info"] as pri:
            return pri.get("pre_pr_migrator_attempts", {}).get(migrator_name, 0)


def run_with_tmpdir(
    context: FeedstockContext,
    migrator: Migrator,
    rerender: bool = True,
    base_branch: str = "main",
    dry_run: bool = False,
    **kwargs: typing.Any,
) -> tuple[MigrationUidTypedDict, dict] | tuple[Literal[False], Literal[False]]:
    """
    For a given feedstock and migration run the migration in a temporary directory that will be deleted after the
    migration is complete.

    The parameters are the same as for the `run` function. The only difference is that you pass a FeedstockContext
    instance instead of a ClonedFeedstockContext instance.

    The exceptions are the same as for the `run` function.
    """
    with context.reserve_clone_directory() as cloned_context:
        return run(
            context=cloned_context,
            migrator=migrator,
            rerender=rerender,
            base_branch=base_branch,
            dry_run=dry_run,
            **kwargs,
        )


def run(
    context: ClonedFeedstockContext,
    migrator: Migrator,
    rerender: bool = True,
    base_branch: str = "main",
    dry_run: bool = False,
    **kwargs: typing.Any,
) -> tuple[MigrationUidTypedDict, dict] | tuple[Literal[False], Literal[False]]:
    """For a given feedstock and migration run the migration

    Parameters
    ----------
    context: ClonedFeedstockContext
        The current feedstock context, already containing information about a temporary directory for the feedstock.
    migrator: Migrator instance
        The migrator to run on the feedstock
    rerender : bool
        Whether to rerender
    base_branch : str, optional
        The base branch to which the PR will be targeted. Defaults to "main".
    kwargs: dict
        The keyword arguments to pass to the migrator.

    Returns
    -------
    migrate_return: MigrationUidTypedDict
        The migration return dict used for tracking finished migrations
    pr_json: dict
        The PR json object for recreating the PR as needed
    """

    # sometimes we get weird directory issues so make sure we reset
    os.chdir(BOT_HOME_DIR)

    # get the repo
    branch_name = migrator.remote_branch(context) + "_h" + uuid4().hex[0:6]

    migrator_name = get_migrator_name(migrator)
    is_version_migration = isinstance(migrator, Version)
    _increment_pre_pr_migrator_attempt(
        context.attrs,
        migrator_name,
        is_version=is_version_migration,
    )

    # TODO: run this in parallel
    repo = get_repo(context=context, branch=branch_name, base_branch=base_branch)

    feedstock_dir = str(context.local_clone_dir)
    if not feedstock_dir or not repo:
        logger.critical(
            "Failed to migrate %s, %s",
            context.feedstock_name,
            context.attrs.get("pr_info", {}).get("bad"),
        )
        return False, False

    # need to use an absolute path here
    feedstock_dir = os.path.abspath(feedstock_dir)

    migration_run_data = run_migration(
        migrator=migrator,
        feedstock_dir=feedstock_dir,
        feedstock_name=context.feedstock_name,
        node_attrs=context.attrs,
        default_branch=context.default_branch,
        **kwargs,
    )

    if not migration_run_data["migrate_return_value"]:
        logger.critical(
            "Failed to migrate %s, %s",
            context.feedstock_name,
            context.attrs.get("pr_info", {}).get("bad"),
        )
        return False, False

    # rerender, maybe
    diffed_files: typing.List[str] = []
    with pushd(feedstock_dir):
        msg = migration_run_data["commit_message"]
        try:
            eval_cmd(["git", "add", "--all", "."])
            if migrator.allow_empty_commits:
                eval_cmd(["git", "commit", "--allow-empty", "-am", msg])
            else:
                eval_cmd(["git", "commit", "-am", msg])
        except CalledProcessError as e:
            logger.info(
                "could not commit to feedstock - "
                "likely no changes - error is '%s'" % (repr(e)),
            )
            # we bail here if we do not plan to rerender and we wanted an empty
            # commit
            # this prevents PRs that don't actually get made from getting marked as done
            if migrator.allow_empty_commits and not rerender:
                raise e

        if rerender:
            head_ref = eval_cmd(["git", "rev-parse", "HEAD"]).strip()
            logger.info("Rerendering the feedstock")

            try:
                rerender_msg = rerender_feedstock(feedstock_dir, timeout=900)
                if rerender_msg is not None:
                    eval_cmd(["git", "commit", "--allow-empty", "-am", rerender_msg])

                make_rerender_comment = False
            except Exception as e:
                # I am trying this bit of code to force these errors
                # to be surfaced in the logs at the right time.
                print(f"RERENDER ERROR: {e}", flush=True)
                if not isinstance(migrator, Version):
                    raise
                else:
                    # for check solvable or automerge, we always raise rerender errors
                    if get_keys_default(
                        context.attrs,
                        ["conda-forge.yml", "bot", "check_solvable"],
                        {},
                        False,
                    ) or get_keys_default(
                        context.attrs,
                        ["conda-forge.yml", "bot", "automerge"],
                        {},
                        False,
                    ):
                        raise
                    else:
                        make_rerender_comment = True

            # If we tried to run the MigrationYaml and rerender did nothing (we only
            # bumped the build number and dropped a yaml file in migrations) bail
            # for instance platform specific migrations
            gdiff = eval_cmd(
                ["git", "diff", "--name-only", f"{head_ref.strip()}...HEAD"]
            )

            diffed_files = [
                _
                for _ in gdiff.split()
                if not (
                    _.startswith("recipe")
                    or _.startswith("migrators")
                    or _.startswith("README")
                )
            ]
        else:
            make_rerender_comment = False

    feedstock_automerge = get_keys_default(
        context.attrs,
        ["conda-forge.yml", "bot", "automerge"],
        {},
        False,
    )
    if isinstance(migrator, Version):
        has_automerge = feedstock_automerge in [True, "version"]
    else:
        has_automerge = getattr(
            migrator, "automerge", False
        ) and feedstock_automerge in [True, "migration"]

    migrator_check_solvable = getattr(migrator, "check_solvable", True)
    feedstock_check_solvable = get_keys_default(
        context.attrs,
        ["conda-forge.yml", "bot", "check_solvable"],
        {},
        False,
    )
    pr_attempts = _get_pre_pr_migrator_attempts(
        context.attrs,
        migrator_name,
        is_version=is_version_migration,
    )
    max_pr_attempts = getattr(
        migrator, "force_pr_after_solver_attempts", MAX_SOLVER_ATTEMPTS * 2
    )

    logger.info(
        f"""automerge and check_solvable status/settings:
    automerge:
        feedstock_automerge: {feedstock_automerge}
        migratror_automerge: {getattr(migrator, 'automerge', False)}
        has_automerge: {has_automerge} (only considers feedstock if version migration)
    check_solvable:
        feedstock_checksolvable: {feedstock_check_solvable}
        migrator_check_solvable: {migrator_check_solvable}
    pre_pr_migrator_attempts: {pr_attempts}
    force_pr_after_solver_attempts: {max_pr_attempts}
"""
    )

    if (
        context.feedstock_name != "conda-forge-pinning"
        and (base_branch == "master" or base_branch == "main")
        # feedstocks that have problematic bootstrapping will not always be solvable
        and context.feedstock_name not in BOOTSTRAP_MAPPINGS
        # stuff in cycles always goes
        and context.attrs["name"] not in getattr(migrator, "cycles", set())
        # stuff at the top always goes
        and context.attrs["name"] not in getattr(migrator, "top_level", set())
        # either the migrator or the feedstock has to request solver checks
        and (migrator_check_solvable or feedstock_check_solvable)
        # we try up to MAX_SOLVER_ATTEMPTS times and then we just skip
        # the solver check and issue the PR if automerge is off
        and (has_automerge or (pr_attempts < max_pr_attempts))
    ):
        solvable, errors, _ = is_recipe_solvable(
            feedstock_dir,
            build_platform=context.attrs["conda-forge.yml"].get(
                "build_platform",
                None,
            ),
        )
        if not solvable:
            ci_url = get_bot_run_url()
            ci_url = f"(<a href='{ci_url}'>bot CI job</a>)" if ci_url else ""
            _solver_err_str = dedent(
                f"""
                not solvable {ci_url} @ {base_branch}
                <details>
                <div align="left">
                <pre>
                {'</pre><pre>'.join(sorted(set(errors)))}
                </pre>
                </div>
                </details>
                """,
            ).strip()

            _set_pre_pr_migrator_error(
                context.attrs,
                migrator_name,
                _solver_err_str,
                is_version=is_version_migration,
            )

            # remove part of a try for solver errors to make those slightly
            # higher priority next time the bot runs
            if isinstance(migrator, Version):
                with context.attrs["version_pr_info"] as vpri:
                    _new_ver = vpri["new_version"]
                    vpri["new_version_attempts"][_new_ver] -= 0.8

            return False, False
        else:
            _reset_pre_pr_migrator_fields(
                context.attrs, migrator_name, is_version=is_version_migration
            )

    # TODO: Better annotation here
    pr_json: typing.Union[MutableMapping, None, bool]
    if (
        isinstance(migrator, MigrationYaml)
        and not diffed_files
        and context.attrs["name"] != "conda-forge-pinning"
    ):
        # spoof this so it looks like the package is done
        pr_json = {
            "state": "closed",
            "merged_at": "never issued",
            "id": str(uuid4()),
        }
    else:
        # push up
        try:
            pr_json = push_repo(
                fctx=context,
                feedstock_dir=feedstock_dir,
                body=migration_run_data["pr_body"],
                repo=repo,
                title=migration_run_data["pr_title"],
                branch=branch_name,
                base_branch=base_branch,
                dry_run=dry_run,
            )

        # This shouldn't happen too often any more since we won't double PR
        except github3.GitHubError as e:
            if e.msg != "Validation Failed":
                raise
            else:
                print(f"Error during push {e}")
                # If we just push to the existing PR then do nothing to the json
                pr_json = False
                ljpr = False

    if pr_json and pr_json["state"] != "closed" and make_rerender_comment:
        comment_on_pr(
            pr_json,
            """\
Hi! This feedstock was not able to be rerendered after the version update changes. I
have pushed the version update changes anyways and am trying to rerender again with this
comment. Hopefully you all can fix this!

@conda-forge-admin rerender""",
            repo,
        )

    if pr_json:
        ljpr = LazyJson(
            os.path.join("pr_json", str(pr_json["id"]) + ".json"),
        )
        with ljpr as __ljpr:
            __ljpr.update(**pr_json)
    else:
        ljpr = False

    # If we've gotten this far then the node is good
    with context.attrs["pr_info"] as pri:
        pri["bad"] = False
    _reset_pre_pr_migrator_fields(
        context.attrs, migrator_name, is_version=is_version_migration
    )

    logger.info("Removing feedstock dir")
    return migration_run_data["migrate_return_value"], ljpr


def _compute_time_per_migrator(mctx, migrators):
    # we weight each migrator by the number of available nodes to migrate
    num_nodes = []
    for migrator in tqdm.tqdm(migrators, ncols=80, desc="computing time per migrator"):
        if isinstance(migrator, Version):
            _num_nodes = 0
            for node_name in migrator.effective_graph.nodes:
                with migrator.effective_graph.nodes[node_name]["payload"] as attrs:
                    with attrs["version_pr_info"] as vpri:
                        _attempts = vpri.get("new_version_attempts", {}).get(
                            vpri.get("new_version", ""),
                            0,
                        )
                    if _attempts < 3:
                        _num_nodes += 1
            _num_nodes = max(
                _num_nodes,
                min(PR_LIMIT * 4, len(migrator.effective_graph.nodes)),
            )
            num_nodes.append(_num_nodes)
        else:
            num_nodes.append(
                min(
                    getattr(migrator, "pr_limit", PR_LIMIT) * 4,
                    len(migrator.effective_graph.nodes),
                ),
            )

    num_nodes_tot = sum(num_nodes)
    # do not divide by zero
    time_per_node = float(os.environ.get("TIMEOUT", 600)) / max(num_nodes_tot, 1)

    # also enforce a minimum of 300 seconds if any nodes can be migrated
    time_per_migrator = []
    for i, migrator in enumerate(migrators):
        _time_per = num_nodes[i] * time_per_node

        if num_nodes[i] > 0 and _time_per < 300:
            _time_per = 300

        time_per_migrator.append(_time_per)

    # finally rescale to fit in the time we have
    tot_time_per_migrator = sum(time_per_migrator)
    if tot_time_per_migrator > 0:
        time_fac = float(os.environ.get("TIMEOUT", 600)) / tot_time_per_migrator
    else:
        time_fac = 1.0
    for i in range(len(time_per_migrator)):
        time_per_migrator[i] = time_per_migrator[i] * time_fac

    # recompute the total here
    tot_time_per_migrator = sum(time_per_migrator)

    return num_nodes, time_per_migrator, tot_time_per_migrator


def _over_time_limit():
    _now = time.time()
    print(
        """\

=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>
=~> elpased time %ds (timeout %ds)
=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>=~>

"""
        % (_now - START_TIME, TIMEOUT),
        flush=True,
        end="",
    )
    return _now - START_TIME > TIMEOUT


def _run_migrator_on_feedstock_branch(
    attrs,
    base_branch,
    migrator,
    fctx,
    dry_run,
    mctx,
    migrator_name,
    good_prs,
):
    break_loop = False
    try:
        try:
            fctx.attrs["new_version"] = attrs.get("version_pr_info", {}).get(
                "new_version", None
            )
            migrator_uid, pr_json = run_with_tmpdir(
                context=fctx,
                migrator=migrator,
                rerender=migrator.rerender,
                hash_type=attrs.get("hash_type", "sha256"),
                base_branch=base_branch,
                dry_run=dry_run,
            )
        finally:
            fctx.attrs.pop("new_version", None)
        # if migration successful
        if migrator_uid:
            with attrs["pr_info"] as pri:
                d = frozen_to_json_friendly(migrator_uid)
                # if we have the PR already do nothing
                if d["data"] in [
                    existing_pr["data"] for existing_pr in pri.get("PRed", [])
                ]:
                    pass
                else:
                    if not pr_json:
                        pr_json = {
                            "state": "closed",
                            "head": {
                                "ref": "<this_is_not_a_branch>",
                            },
                        }
                    d["PR"] = pr_json
                    if "PRed" not in pri:
                        pri["PRed"] = []
                    pri["PRed"].append(d)
                pri.update(
                    {
                        "smithy_version": mctx.smithy_version,
                        "pinning_version": mctx.pinning_version,
                    },
                )

    except (github3.GitHubError, github.GithubException) as e:
        if hasattr(e, "msg") and e.msg == "Repository was archived so is read-only.":
            attrs["archived"] = True
        else:
            logger.critical(
                "GITHUB ERROR ON FEEDSTOCK: %s",
                fctx.feedstock_name,
            )

            if is_github_api_limit_reached():
                logger.warning("GitHub API error", exc_info=e)
                break_loop = True

    except VersionMigrationError as e:
        logger.exception("VERSION MIGRATION ERROR")

        _set_pre_pr_migrator_error(
            attrs,
            migrator_name,
            str(
                e
            ),  # we do not use any HTML formats here since at one point status page had them
            is_version=isinstance(migrator, Version),
        )

    except URLError as e:
        logger.exception("URLError ERROR")
        with attrs["pr_info"] as pri:
            pri["bad"] = {
                "exception": str(e),
                "traceback": str(traceback.format_exc()).split(
                    "\n",
                ),
                "code": getattr(e, "code"),
                "url": getattr(e, "url"),
            }

        _set_pre_pr_migrator_error(
            attrs,
            migrator_name,
            sanitize_string(
                "bot error (%s): %s: %s"
                % (
                    '<a href="' + get_bot_run_url() + '">bot CI job</a>',
                    base_branch,
                    str(traceback.format_exc()),
                ),
            ),
            is_version=isinstance(migrator, Version),
        )
    except Exception as e:
        logger.exception("NON GITHUB ERROR")

        # we don't set bad for rerendering errors
        if "conda smithy rerender -c auto --no-check-uptodate" not in str(e):
            with attrs["pr_info"] as pri:
                pri["bad"] = {
                    "exception": str(e),
                    "traceback": str(traceback.format_exc()).split(
                        "\n",
                    ),
                }

        if isinstance(e, ContainerRuntimeError):
            _err_str = str(e)
        else:
            _err_str = str(traceback.format_exc())

        _set_pre_pr_migrator_error(
            attrs,
            migrator_name,
            sanitize_string(
                "bot error (%s): %s:\n%s"
                % (
                    '<a href="' + get_bot_run_url() + '">bot CI job</a>',
                    base_branch,
                    _err_str,
                ),
            ),
            is_version=isinstance(migrator, Version),
        )
    else:
        if migrator_uid:
            # On successful PR add to our counter
            good_prs += 1

    return good_prs, break_loop


def _is_migrator_done(_mg_start, good_prs, time_per, pr_limit):
    curr_time = time.time()
    backend = github_backend()
    api_req = backend.get_api_requests_left()

    if curr_time - START_TIME > TIMEOUT:
        logger.info(
            "BOT TIMEOUT: breaking after %d seconds (limit %d)",
            curr_time - START_TIME,
            TIMEOUT,
        )
        return True

    if good_prs >= pr_limit:
        logger.info(
            "MIGRATOR PR LIMIT: breaking after %d good PRs (limit %d)",
            good_prs,
            pr_limit,
        )
        return True

    if (curr_time - _mg_start) > time_per:
        logger.info(
            "TIME LIMIT: breaking after %d seconds (limit %d)",
            curr_time - _mg_start,
            time_per,
        )
        return True

    if api_req == 0:
        logger.info(
            "GitHub API LIMIT: no requests left",
        )
        return True

    return False


def _run_migrator(migrator, mctx, temp, time_per, dry_run):
    _mg_start = time.time()

    migrator_name = get_migrator_name(migrator)

    if hasattr(migrator, "name"):
        extra_name = "-%s" % migrator.name
    else:
        extra_name = ""

    with fold_log_lines(
        "migrations for %s%s\n"
        % (
            migrator.__class__.__name__,
            extra_name,
        ),
    ):
        good_prs = 0
        effective_graph = migrator.effective_graph

        possible_nodes = list(migrator.order(effective_graph, mctx.graph))

        # version debugging info
        if isinstance(migrator, Version):
            print("possible version migrations:", flush=True)
            for node_name in possible_nodes:
                with effective_graph.nodes[node_name]["payload"] as attrs:
                    with attrs["version_pr_info"] as vpri:
                        print(
                            "    node|curr|new|attempts: %s|%s|%s|%f"
                            % (
                                node_name,
                                attrs.get("version"),
                                vpri.get("new_version"),
                                (
                                    vpri.get("new_version_attempts", {}).get(
                                        vpri.get("new_version", ""),
                                        0,
                                    )
                                ),
                            ),
                            flush=True,
                        )

        print(
            "found %d nodes for migration %s%s"
            % (
                len(effective_graph.nodes),
                migrator.__class__.__name__,
                extra_name,
            ),
            flush=True,
        )

        if _is_migrator_done(_mg_start, good_prs, time_per, migrator.pr_limit):
            return 0

    for node_name in possible_nodes:
        with (
            fold_log_lines(
                "%s%s IS MIGRATING %s"
                % (
                    migrator.__class__.__name__.upper(),
                    extra_name,
                    node_name,
                )
            ),
            mctx.graph.nodes[node_name]["payload"] as attrs,
        ):
            # Don't let CI timeout, break ahead of the timeout so we make certain
            # to write to the repo
            if _is_migrator_done(_mg_start, good_prs, time_per, migrator.pr_limit):
                break

            base_branches = migrator.get_possible_feedstock_branches(attrs)
            if "branch" in attrs:
                has_attrs_branch = True
                orig_branch = attrs.get("branch")
            else:
                has_attrs_branch = False
                orig_branch = None

            fctx = FeedstockContext(
                feedstock_name=attrs["feedstock_name"],
                attrs=attrs,
            )

            # map main to current default branch
            base_branches = [
                br if br != "main" else fctx.default_branch for br in base_branches
            ]

            try:
                for base_branch in base_branches:
                    # skip things that do not get migrated
                    attrs["branch"] = base_branch
                    if migrator.filter(attrs):
                        if (
                            logging.getLogger("conda_forge_tick").getEffectiveLevel()
                            > logging.DEBUG
                        ):
                            with change_log_level("conda_forge_tick", "DEBUG"):
                                migrator.filter(attrs)
                        logger.info(
                            "skipping node %s w/ branch %s", node_name, base_branch
                        )
                        continue

                    with fold_log_lines(
                        "%s%s IS MIGRATING %s:%s"
                        % (
                            migrator.__class__.__name__.upper(),
                            extra_name,
                            fctx.feedstock_name,
                            base_branch,
                        )
                    ):
                        good_prs, break_loop = _run_migrator_on_feedstock_branch(
                            attrs,
                            base_branch,
                            migrator,
                            fctx,
                            dry_run,
                            mctx,
                            migrator_name,
                            good_prs,
                        )
                        if break_loop:
                            break
            finally:
                # reset branch
                if has_attrs_branch:
                    attrs["branch"] = orig_branch

                # do this but it is crazy
                gc.collect()

                # sometimes we get weird directory issues so make sure we reset
                os.chdir(BOT_HOME_DIR)

                # Write graph partially through
                if not dry_run:
                    dump_graph(mctx.graph)

                with filter_reprinted_lines("rm-tmp"):
                    for f in glob.glob("/tmp/*"):
                        if f not in temp:
                            try:
                                eval_cmd(["rm", "-rf", f])
                            except Exception:
                                pass

    return good_prs


def _setup_limits():
    import resource

    if "MEMORY_LIMIT_GB" in os.environ:
        limit_gb = float(os.environ["MEMORY_LIMIT_GB"])
        limit = limit_gb * 1e9
        limit_int = int(int(limit) * 0.95)
        print(f"limit read as {limit / 1e9} GB")
        print(f"Setting memory limit to {limit_int // 1e9} GB")
        resource.setrlimit(resource.RLIMIT_AS, (limit_int, limit_int))


def _update_nodes_with_bot_rerun(gx: nx.DiGraph):
    """Go through all the open PRs and check if they are rerun"""

    print("processing bot-rerun labels", flush=True)

    for i, (name, node) in enumerate(gx.nodes.items()):
        # logger.info(
        #     f"node: {i} memory usage: "
        #     f"{psutil.Process().memory_info().rss // 1024 ** 2}MB",
        # )
        with node["payload"] as payload:
            if payload.get("archived", False):
                continue
            with payload["pr_info"] as pri, payload["version_pr_info"] as vpri:
                # reset bad
                pri["bad"] = False
                vpri["bad"] = False

                for __pri in [pri, vpri]:
                    for migration in __pri.get("PRed", []):
                        try:
                            pr_json = migration.get("PR", {})
                            # maybe add a pass check info here ? (if using DEBUG)
                        except Exception as e:
                            logger.error(
                                f"BOT-RERUN : could not proceed check with {node}, {e}",
                            )
                            raise e
                        # if there is a valid PR and it isn't currently listed as rerun
                        # but the PR needs a rerun
                        if (
                            pr_json
                            and not migration["data"]["bot_rerun"]
                            and "bot-rerun"
                            in [lb["name"] for lb in pr_json.get("labels", [])]
                        ):
                            migration["data"]["bot_rerun"] = time.time()
                            logger.info(
                                "BOT-RERUN %s: processing bot rerun label "
                                "for migration %s",
                                name,
                                migration["data"],
                            )


def _filter_ignored_versions(attrs, version):
    versions_to_ignore = get_keys_default(
        attrs,
        ["conda-forge.yml", "bot", "version_updates", "exclude"],
        {},
        [],
    )
    if (
        str(version).replace("-", ".") in versions_to_ignore
        or str(version) in versions_to_ignore
    ):
        return False
    else:
        return version


def _update_nodes_with_new_versions(gx):
    """Updates every node with it's new version (when available)"""

    print("updating nodes with new versions", flush=True)

    version_nodes = get_all_keys_for_hashmap("versions")

    for node in version_nodes:
        version_data = LazyJson(f"versions/{node}.json").data
        with gx.nodes[f"{node}"]["payload"] as attrs:
            if attrs.get("archived", False):
                continue
            with attrs["version_pr_info"] as vpri:
                version_from_data = version_data.get("new_version", False)
                version_from_attrs = _filter_ignored_versions(
                    attrs,
                    vpri.get("new_version", False),
                )
                # don't update the version if it isn't newer
                if version_from_data and isinstance(version_from_data, str):
                    # we only override the graph node if the version we found is newer
                    # or the graph doesn't have a valid version
                    if isinstance(version_from_attrs, str):
                        vpri["new_version"] = max(
                            [version_from_data, version_from_attrs],
                            key=lambda x: VersionOrder(x.replace("-", ".")),
                        )
                    else:
                        vpri["new_version"] = version_from_data


def _remove_closed_pr_json():
    print("collapsing closed PR json", flush=True)

    # first we go from nodes to pr json and update the pr info and remove the data
    name_nodes = [
        ("pr_info", get_all_keys_for_hashmap("pr_info")),
        ("version_pr_info", get_all_keys_for_hashmap("version_pr_info")),
    ]
    for name, nodes in name_nodes:
        for node in nodes:
            lzj_pri = LazyJson(f"{name}/{node}.json")
            with lazy_json_transaction():
                with lzj_pri as pri:
                    for pr_ind in range(len(pri.get("PRed", []))):
                        pr = pri["PRed"][pr_ind].get("PR", None)
                        if (
                            pr is not None
                            and isinstance(pr, LazyJson)
                            and (pr.get("state", None) == "closed" or pr.data == {})
                        ):
                            pri["PRed"][pr_ind]["PR"] = {
                                "state": "closed",
                                "number": pr.get("number", None),
                                "labels": [
                                    {"name": lb["name"]} for lb in pr.get("labels", [])
                                ],
                            }
                            assert len(pr.file_name.split("/")) == 2
                            assert pr.file_name.split("/")[0] == "pr_json"
                            assert pr.file_name.split("/")[1].endswith(".json")
                            pr_json_node = pr.file_name.split("/")[1][: -len(".json")]
                            del pr
                            remove_key_for_hashmap(
                                "pr_json",
                                pr_json_node,
                            )

    # at this point, any json blob referenced in the pr info is state != closed
    # so we can remove anything that is empty or closed
    nodes = get_all_keys_for_hashmap("pr_json")
    for node in nodes:
        pr = LazyJson(f"pr_json/{node}.json")
        if pr.get("state", None) == "closed" or pr.data == {}:
            remove_key_for_hashmap(
                pr.file_name.split("/")[0],
                pr.file_name.split("/")[1][: -len(".json")],
            )


def _update_graph_with_pr_info():
    _remove_closed_pr_json()
    gx = load_existing_graph()
    _update_nodes_with_bot_rerun(gx)
    _update_nodes_with_new_versions(gx)
    dump_graph(gx)


def main(ctx: CliContext) -> None:
    global START_TIME
    START_TIME = time.time()

    _setup_limits()

    with fold_log_lines("updating graph with PR info"):
        _update_graph_with_pr_info()
        deploy(ctx, dirs_to_deploy=["version_pr_info", "pr_json", "pr_info"])

    # record tmp dir so we can be sure to clean it later
    temp = glob.glob("/tmp/*")

    with fold_log_lines("loading graph and migrators"):
        gx = load_existing_graph()
        smithy_version: str = eval_cmd(["conda", "smithy", "--version"]).strip()
        pinning_version: str = cast(
            str,
            json.loads(eval_cmd(["conda", "list", "conda-forge-pinning", "--json"]))[0][
                "version"
            ],
        )
        mctx = MigratorSessionContext(
            graph=gx,
            smithy_version=smithy_version,
            pinning_version=pinning_version,
            dry_run=ctx.dry_run,
        )
        migrators = load_migrators()

    # compute the time per migrator
    with fold_log_lines("computing migrator run times"):
        print("computing time per migration", flush=True)
        (
            num_nodes,
            time_per_migrator,
            tot_time_per_migrator,
        ) = _compute_time_per_migrator(
            mctx,
            migrators,
        )
        for i, migrator in enumerate(migrators):
            if hasattr(migrator, "name"):
                extra_name = "-%s" % migrator.name
            else:
                extra_name = ""

            print(
                "    %s%s: %d - gets %f seconds (%f percent)"
                % (
                    migrator.__class__.__name__,
                    extra_name,
                    num_nodes[i],
                    time_per_migrator[i],
                    time_per_migrator[i] / max(tot_time_per_migrator, 1) * 100,
                ),
                flush=True,
            )

    for mg_ind, migrator in enumerate(migrators):
        good_prs = _run_migrator(
            migrator,
            mctx,
            temp,
            time_per_migrator[mg_ind],
            ctx.dry_run,
        )
        if good_prs > 0:
            pass
            # this has been causing issues with bad deploys
            # turning off for now
            # deploy(
            #     ctx,
            #     dirs_to_deploy=[
            #         "pr_json",
            #         "pr_info",
            #         "version_pr_info",
            #     ],
            # )

    logger.info("API Calls Remaining: %d", github_backend().get_api_requests_left())
    logger.info("Done")
