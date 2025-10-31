import glob
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager

import wurlitzer
from conda_forge_feedstock_ops.container_utils import (
    get_default_log_level_args,
    run_container_operation,
    should_use_container,
)
from conda_forge_feedstock_ops.os_utils import chmod_plus_rwX, sync_dirs

from conda_forge_tick.settings import (
    ENV_CONDA_FORGE_ORG,
    ENV_GRAPH_GITHUB_BACKEND_REPO,
    settings,
)

logger = logging.getLogger(__name__)

CONDA_BUILD_SPECIAL_KEYS = (
    "pin_run_as_build",
    "ignore_version",
    "ignore_build_only_deps",
    "extend_keys",
    "zip_keys",
)


@contextmanager
def provide_source_code(recipe_dir, use_container=None):
    """Context manager to provide the source code for a recipe.

    Parameters
    ----------
    recipe_dir : str
        The path to the recipe directory.
    use_container : bool, optional
        Whether to use a container to run the version parsing.
        If None, the function will use a container if the environment
        variable `CF_FEEDSTOCK_OPS_IN_CONTAINER` is 'false'. This feature can be
        used to avoid container in container calls.

    Yields
    ------
    str
        The path to the source code directory.
    """
    if should_use_container(use_container=use_container):
        with provide_source_code_containerized(recipe_dir) as source_dir:
            yield source_dir
    else:
        with provide_source_code_local(recipe_dir) as source_dir:
            yield source_dir


@contextmanager
def provide_source_code_containerized(recipe_dir):
    """Context manager to provide the source code for a recipe.

    **This function runs recipe parsing in a container and then provides
    the source code in a tmpdir on the host.**

    Parameters
    ----------
    recipe_dir : str
        The path to the recipe directory.

    Yields
    ------
    str
        The path to the source code directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_recipe_dir = os.path.join(tmpdir, "recipe_dir")
        sync_dirs(recipe_dir, tmp_recipe_dir, ignore_dot_git=True, update_git=False)

        chmod_plus_rwX(tmpdir)

        logger.debug("host recipe dir %s: %s", recipe_dir, os.listdir(recipe_dir))
        logger.debug(
            "copied host recipe dir %s: %s",
            tmp_recipe_dir,
            os.listdir(tmp_recipe_dir),
        )

        tmp_source_dir = os.path.join(tmpdir, "source_dir")

        args = [
            "conda-forge-tick-container",
            "provide-source-code",
        ]
        args += get_default_log_level_args(logger)

        run_container_operation(
            args,
            mount_readonly=False,
            mount_dir=tmpdir,
            extra_container_args=[
                "-e",
                f"{ENV_CONDA_FORGE_ORG}={settings().conda_forge_org}",
                "-e",
                f"{ENV_GRAPH_GITHUB_BACKEND_REPO}={settings().graph_github_backend_repo}",
            ],
        )

        yield tmp_source_dir

        # When tempfile removes tempdir, it tries to reset permissions on subdirs.
        # This causes a permission error since the subdirs were made by the user
        # in the container. So we remove the subdir we made before cleaning up.
        shutil.rmtree(tmp_recipe_dir)
        shutil.rmtree(tmp_source_dir)


@contextmanager
def provide_source_code_local(recipe_dir):
    """Context manager to provide the source code for a recipe.

    Parameters
    ----------
    recipe_dir : str
        The path to the recipe directory.

    Returns
    -------
    str
        The path to the source code directory.

    Raises
    ------
    RuntimeError
        If there is an error in getting the conda build source code or printing it.
    """
    try:
        with wurlitzer.pipes(stderr=wurlitzer.STDOUT) as (out, _):
            from conda_build.api import render
            from conda_build.config import get_or_merge_config
            from conda_build.source import provide

            # Use conda build to do all the downloading/extracting bits
            config = get_or_merge_config(None)
            ci_support_files = sorted(
                glob.glob(os.path.join(recipe_dir, "../.ci_support/*.yaml"))
            )
            if ci_support_files:
                config.variant_config_files = [ci_support_files[0]]
            else:
                config.variant_config_files = [
                    # try global pinnings
                    os.path.join(os.environ["CONDA_PREFIX"], "conda_build_config.yaml")
                ]

            md = render(
                recipe_dir,
                config=config,
                finalize=False,
                bypass_env_check=True,
            )
            if not md:
                return None
            md = md[0][0]

            # provide source dir
            yield provide(md)
    except (SystemExit, Exception) as e:
        logger.error("Error in getting conda build src!", exc_info=e)
        raise RuntimeError("conda build src exception: " + str(e))
