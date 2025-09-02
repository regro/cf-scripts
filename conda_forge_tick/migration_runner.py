import logging
import os
import shutil
import tempfile
from pathlib import Path

import orjson
from conda_forge_feedstock_ops.container_utils import (
    get_default_log_level_args,
    run_container_operation,
    should_use_container,
)
from conda_forge_feedstock_ops.os_utils import (
    chmod_plus_rwX,
    get_user_execute_permissions,
    reset_permissions_with_user_execute,
    sync_dirs,
)

from conda_forge_tick.contexts import ClonedFeedstockContext
from conda_forge_tick.lazy_json_backends import LazyJson, dumps
from conda_forge_tick.settings import (
    ENV_CONDA_FORGE_ORG,
    ENV_GRAPH_GITHUB_BACKEND_REPO,
    settings,
)

logger = logging.getLogger(__name__)


def run_migration(
    *,
    migrator,
    feedstock_dir,
    feedstock_name,
    node_attrs,
    default_branch,
    use_container=None,
    **kwargs,
):
    """Run a migration against a feedstock.

    Parameters
    ----------
    migrator : Migrator
        The migrator to run.
    feedstock_dir : str
        The path to the feedstock directory.
    feedstock_name : str
        The name of the feedstock.
    node_attrs : dict
        The node attributes for the feedstock.
    default_branch : str
        The default branch of the feedstock.
    use_container : bool, optional
        Whether to use a container to run the version parsing.
        If None, the function will use a container if the environment
        variable `CF_FEEDSTOCK_OPS_IN_CONTAINER` is 'false'. This feature can be
        used to avoid container in container calls.
    **kwargs : dict
        Additional keyword arguments to pass to the migration.

    Returns
    -------
    data : dict
        Data for the migration with keys:
          - migrate_return_value: The return value of the migration.
          - commit_message: The commit message for the migration.
          - pr_title: The PR title for the migration.
          - pr_body: The PR body for the migration.
    """
    if should_use_container(use_container=use_container):
        return run_migration_containerized(
            migrator=migrator,
            feedstock_dir=feedstock_dir,
            feedstock_name=feedstock_name,
            node_attrs=node_attrs,
            default_branch=default_branch,
            **kwargs,
        )
    else:
        return run_migration_local(
            migrator=migrator,
            feedstock_dir=feedstock_dir,
            feedstock_name=feedstock_name,
            node_attrs=node_attrs,
            default_branch=default_branch,
            **kwargs,
        )


def run_migration_containerized(
    *,
    migrator,
    feedstock_dir,
    feedstock_name,
    node_attrs,
    default_branch,
    **kwargs,
):
    """Run a migration against a feedstock.

    **This function runs the migration in a container.**

    Parameters
    ----------
    migrator : Migrator
        The migrator to run.
    feedstock_dir : str
        The path to the feedstock directory.
    feedstock_name : str
        The name of the feedstock.
    node_attrs : dict
        The node attributes for the feedstock.
    default_branch : str
        The default branch of the feedstock.
    use_container : bool, optional
        Whether to run the migration in a container, by default True.
    **kwargs : dict
        Additional keyword arguments to pass to the migration.

    Returns
    -------
    data : dict
        Data for the migration with keys:
          - migrate_return_value: The return value of the migration.
          - commit_message: The commit message for the migration.
          - pr_title: The PR title for the migration.
          - pr_body: The PR body for the migration.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_feedstock_dir = os.path.join(tmpdir, os.path.basename(feedstock_dir))
        sync_dirs(
            feedstock_dir, tmp_feedstock_dir, ignore_dot_git=True, update_git=False
        )

        perms = get_user_execute_permissions(feedstock_dir)
        with open(
            os.path.join(tmpdir, f"permissions-{os.path.basename(feedstock_dir)}.json"),
            "wb",
        ) as f:
            f.write(orjson.dumps(perms))

        chmod_plus_rwX(tmpdir, recursive=True)

        logger.debug(
            "host feedstock dir %s: %s", feedstock_dir, os.listdir(feedstock_dir)
        )
        logger.debug(
            "copied host feedstock dir %s: %s",
            tmp_feedstock_dir,
            os.listdir(tmp_feedstock_dir),
        )

        mfile = os.path.join(tmpdir, "migrator.json")
        with open(mfile, "w") as f:
            f.write(dumps(migrator.to_lazy_json_data()))

        args = [
            "conda-forge-tick-container",
            "migrate-feedstock",
            "--feedstock-name",
            feedstock_name,
            "--default-branch",
            default_branch,
            "--existing-feedstock-node-attrs",
            "-",
        ]
        args += get_default_log_level_args(logger)

        if kwargs:
            args += ["--kwargs", dumps(kwargs)]

        data = run_container_operation(
            args,
            mount_readonly=False,
            mount_dir=tmpdir,
            input=(
                dumps(node_attrs.data)
                if isinstance(node_attrs, LazyJson)
                else dumps(node_attrs)
            ),
            extra_container_args=[
                "-e",
                "RUN_URL",
                "-e",
                f"{ENV_CONDA_FORGE_ORG}={settings().conda_forge_org}",
                "-e",
                f"{ENV_GRAPH_GITHUB_BACKEND_REPO}={settings().graph_github_backend_repo}",
            ],
        )

        sync_dirs(
            tmp_feedstock_dir,
            feedstock_dir,
            ignore_dot_git=True,
            update_git=False,
        )
        reset_permissions_with_user_execute(feedstock_dir, data["permissions"])

        # When tempfile removes tempdir, it tries to reset permissions on subdirs.
        # This causes a permission error since the subdirs were made by the user
        # in the container. So we remove the subdir we made before cleaning up.
        shutil.rmtree(tmp_feedstock_dir)

    data.pop("permissions", None)
    return data


def run_migration_local(
    *,
    migrator,
    feedstock_dir,
    feedstock_name,
    node_attrs,
    default_branch,
    **kwargs,
):
    """Run a migration against a feedstock.

    Parameters
    ----------
    migrator : Migrator
        The migrator to run.
    feedstock_dir : str
        The path to the feedstock directory.
    feedstock_name : str
        The name of the feedstock.
    node_attrs : dict
        The node attributes for the feedstock.
    default_branch : str
        The default branch of the feedstock.
    use_container : bool, optional
        Whether to run the migration in a container, by default True.
    **kwargs : dict
        Additional keyword arguments to pass to the migration.

    Returns
    -------
    data : dict
        Data for the migration with keys:
          - migrate_return_value: The return value of the migration.
          - commit_message: The commit message for the migration.
          - pr_title: The PR title for the migration.
          - pr_body: The PR body for the migration.
    """
    # Instead of mimicking the ClonedFeedstockContext which is already available in the call hierarchy of this function,
    # we should instead pass the ClonedFeedstockContext object to this function. This would allow the following issue.
    # POSSIBLE BUG: The feedstock_ctx object is mimicked and any attributes not listed here might have incorrect
    # default values that were actually overridden. FOR EXAMPLE, DO NOT use the git_repo_owner attribute of the
    # feedstock_ctx object below. Instead, refactor to make this function accept a ClonedFeedstockContext object.
    feedstock_ctx = ClonedFeedstockContext(
        feedstock_name=feedstock_name,
        attrs=node_attrs,
        default_branch=default_branch,
        local_clone_dir=Path(feedstock_dir),
    )
    recipe_dir = os.path.join(feedstock_dir, "recipe")

    data = {
        "migrate_return_value": None,
        "commit_message": None,
        "pr_title": None,
        "pr_body": None,
    }

    migrator.run_pre_piggyback_migrations(recipe_dir, feedstock_ctx.attrs, **kwargs)

    data["migrate_return_value"] = migrator.migrate(
        recipe_dir, feedstock_ctx.attrs, **kwargs
    )
    if not data["migrate_return_value"]:
        return data

    migrator.run_post_piggyback_migrations(recipe_dir, feedstock_ctx.attrs, **kwargs)

    data["commit_message"] = migrator.commit_message(feedstock_ctx)
    data["pr_body"] = migrator.pr_body(feedstock_ctx)
    data["pr_title"] = migrator.pr_title(feedstock_ctx)

    return data
