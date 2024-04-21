import logging
import os
import tempfile
from contextlib import contextmanager

from conda_forge_tick.os_utils import sync_dirs, chmod_plus_rwX
from conda_forge_tick.utils import CB_CONFIG, run_container_task

logger = logging.getLogger(__name__)


@contextmanager
def provide_source_code(recipe_dir, use_container=True):
    """Context manager to provide the source code for a recipe.

    Parameters
    ----------
    recipe_dir : str
        The path to the recipe directory.

    Returns
    -------
    str
        The path to the source code directory.
    """

    in_container = os.environ.get("CF_TICK_IN_CONTAINER", "false") == "true"
    if use_container is None:
        use_container = not in_container

    if use_container and not in_container:
        with provide_source_code_containerized(recipe_dir) as source_dir:
            yield source_dir
    else:
        with provide_source_code_local(recipe_dir) as source_dir:
            yield source_dir


@contextmanager
def provide_source_code_containerized(recipe_dir, use_container=True):
    """Context manager to provide the source code for a recipe.

    **This function runs recipe parsing in a container and then provides
    the source code in a tmpdir on the host.**

    Parameters
    ----------
    recipe_dir : str
        The path to the recipe directory.

    Returns
    -------
    str
        The path to the source code directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_recipe_dir = os.path.join(tmpdir, "recipe_dir")
        sync_dirs(recipe_dir, tmp_recipe_dir, ignore_dot_git=True, update_git=False)

        chmod_plus_rwX(tmpdir)

        logger.info(f"host recipe dir {recipe_dir}: {os.listdir(recipe_dir)}")
        logger.info(
            f"copied host recipe dir {tmp_recipe_dir}: {os.listdir(tmp_recipe_dir)}"
        )

        run_container_task(
            "provide-source-code",
            [],
            mount_readonly=False,
            mount_dir=tmpdir,
        )

        yield os.path.join(tmpdir, "source_dir")


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
    """
    try:
        from conda_build.api import render
        from conda_build.config import Config
        from conda_build.source import provide

        # Use conda build to do all the downloading/extracting bits
        md = render(
            recipe_dir,
            config=Config(**CB_CONFIG),
            finalize=False,
            bypass_env_check=True,
        )
        if not md:
            return None
        md = md[0][0]

        # provide source dir
        yield provide(md)
    except (SystemExit, Exception) as e:
        raise RuntimeError("conda build src exception:" + str(e))
