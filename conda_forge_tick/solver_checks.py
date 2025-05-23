import logging
import os
import shutil
import tempfile

import orjson
from conda_forge_feedstock_ops.container_utils import (
    get_default_log_level_args,
    run_container_operation,
    should_use_container,
)
from conda_forge_feedstock_ops.os_utils import sync_dirs

from conda_forge_tick.settings import (
    ENV_CONDA_FORGE_ORG,
    ENV_GRAPH_GITHUB_BACKEND_REPO,
    settings,
)

logger = logging.getLogger(__name__)


def is_recipe_solvable(
    feedstock_dir,
    additional_channels=None,
    timeout=600,
    verbosity=None,
    build_platform=None,
    use_container=None,
):
    """Compute if a recipe is solvable.

    We look through each of the conda build configs in the feedstock
    .ci_support dir and test each ones host and run requirements.
    The final result is a logical AND of all of the results for each CI
    support config.

    Parameters
    ----------
    feedstock_dir : str
        The directory of the feedstock.
    additional_channels : list of str, optional
        If given, these channels will be used in addition to the main ones.
    timeout : int, optional
        If not None, then the work will be run in a separate process and
        this function will return True if the work doesn't complete before `timeout`
        seconds.
    verbosity : int
        An int indicating the level of verbosity from 0 (no output) to 3
        (gobbs of output).
    build_platform : dict, optional
        The `build_platform` section of the `conda-forge.yml` file.`
    use_container : bool, optional
        Whether to use a container to run the version parsing.
        If None, the function will use a container if the environment
        variable `CF_FEEDSTOCK_OPS_IN_CONTAINER` is 'false'. This feature can be
        used to avoid container in container calls.

    Returns
    -------
    solvable : bool
        The logical AND of the solvability of the recipe on all platforms
        in the CI scripts.
    errors : list of str
        A list of errors from mamba. Empty if recipe is solvable.
    solvable_by_variant : dict
        A lookup by variant config that shows if a particular config is solvable
    """
    if verbosity is None:
        _log2verb = {
            "CRITICAL": 0,
            "WARNING": 1,
            "INFO": 2,
            "DEBUG": 3,
        }
        verbosity = _log2verb.get(
            str(logging.getLevelName(logger.getEffectiveLevel())).upper()
        )
        logger.debug(
            "is_recipe_solver log-level=%d -> verbosity=%d",
            logging.getLevelName(logger.getEffectiveLevel()),
            verbosity,
        )

    if should_use_container(use_container=use_container):
        return _is_recipe_solvable_containerized(
            feedstock_dir,
            additional_channels=additional_channels,
            timeout=timeout,
            build_platform=build_platform,
            verbosity=verbosity,
        )
    else:
        from conda_forge_feedstock_check_solvable import (
            is_recipe_solvable as _is_recipe_solvable,
        )

        return _is_recipe_solvable(
            feedstock_dir,
            additional_channels=additional_channels,
            timeout=timeout,
            build_platform=build_platform,
            verbosity=verbosity,
        )


def _is_recipe_solvable_containerized(
    feedstock_dir,
    additional_channels=None,
    timeout=600,
    build_platform=None,
    verbosity=1,
):
    """Compute if a recipe is solvable.

    **This function runs the rerender in a container.**

    See the docstring of `is_recipe_solvable` for inputs and outputs.
    """
    args = [
        "conda-forge-tick-container",
        "check-solvable",
        "--timeout",
        str(timeout),
        "--verbosity",
        str(verbosity),
    ]
    args += get_default_log_level_args(logger)

    if additional_channels:
        args += ["--additional-channels", ",".join(additional_channels)]

    if build_platform:
        args += ["--build-platform", orjson.dumps(build_platform).decode("utf-8")]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_feedstock_dir = os.path.join(tmpdir, os.path.basename(feedstock_dir))
        sync_dirs(
            feedstock_dir, tmp_feedstock_dir, ignore_dot_git=True, update_git=False
        )

        logger.debug(
            "host feedstock dir %s: %s", feedstock_dir, os.listdir(feedstock_dir)
        )
        logger.debug(
            "copied host feedstock dir %s: %s",
            tmp_feedstock_dir,
            os.listdir(tmp_feedstock_dir),
        )

        data = run_container_operation(
            args,
            mount_readonly=True,
            mount_dir=tmp_feedstock_dir,
            extra_container_args=[
                "-e",
                f"{ENV_CONDA_FORGE_ORG}={settings().conda_forge_org}",
                "-e",
                f"{ENV_GRAPH_GITHUB_BACKEND_REPO}={settings().graph_github_backend_repo}",
            ],
        )

        # When tempfile removes tempdir, it tries to reset permissions on subdirs.
        # This causes a permission error since the subdirs were made by the user
        # in the container. So we remove the subdir we made before cleaning up.
        shutil.rmtree(tmp_feedstock_dir)

    return data["solvable"], data["errors"], data["solvable_by_variant"]
