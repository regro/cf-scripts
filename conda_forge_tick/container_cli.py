#!/usr/bin/env python
"""Run specific tasks for the bot.

All imports from the bot need to be guarded by putting them in the subcommands.
This ensures that we can set important environment variables before any imports,
including `CONDA_BLD_PATH`.

This container is run in a read-only environment except a small tmpfs volume
mounted at `/tmp`. The `TMPDIR` environment variable is set to `/tmp` so that
one can use the `tempfile` module to create temporary files and directories.

These tasks return their info to the bot by printing a JSON blob to stdout.
"""

import copy
import glob
import logging
import os
import subprocess
import sys
import tempfile
import traceback
from contextlib import contextmanager, redirect_stdout

import click
import orjson

existing_feedstock_node_attrs_option = click.option(
    "--existing-feedstock-node-attrs",
    required=True,
    type=str,
    help=(
        "The existing feedstock node attrs JSON as a string "
        "or the name of the feedstock. The data will be downloaded "
        "from the bot metadata if a feedstock name is passed."
    ),
)
log_level_option = click.option(
    "--log-level",
    default="info",
    type=click.Choice(["debug", "info", "warning", "error", "critical"]),
    help="The log level to use.",
)


@contextmanager
def _setenv(name, value):
    """Set an environment variable temporarily."""
    old = os.environ.get(name)
    try:
        os.environ[name] = value
        yield
    finally:
        if old is None:
            del os.environ[name]
        else:
            os.environ[name] = old


def _get_existing_feedstock_node_attrs(existing_feedstock_node_attrs):
    from conda_forge_tick.lazy_json_backends import (
        LazyJson,
        lazy_json_override_backends,
        loads,
    )

    if existing_feedstock_node_attrs == "-":
        val = sys.stdin.read()
        attrs = loads(val)
    elif existing_feedstock_node_attrs.startswith("{"):
        attrs = loads(existing_feedstock_node_attrs)
    else:
        if not existing_feedstock_node_attrs.endswith(".json"):
            existing_feedstock_node_attrs += ".json"

        pth = os.path.join("node_attrs", existing_feedstock_node_attrs)
        with (
            lazy_json_override_backends(["github"], use_file_cache=False),
            LazyJson(pth) as lzj,
        ):
            attrs = copy.deepcopy(lzj.data)

    return attrs


def _run_bot_task(func, *, log_level: str, existing_feedstock_node_attrs, **kwargs):
    with (
        tempfile.TemporaryDirectory() as tmpdir_cbld,
        _setenv("CONDA_BLD_PATH", os.path.join(tmpdir_cbld, "conda-bld")),
        tempfile.TemporaryDirectory() as tmpdir_cache,
        _setenv("XDG_CACHE_HOME", tmpdir_cache),
        tempfile.TemporaryDirectory() as tmpdir_conda_pkgs_dirs,
        _setenv("CONDA_PKGS_DIRS", tmpdir_conda_pkgs_dirs),
    ):
        os.makedirs(os.path.join(tmpdir_cbld, "conda-bld"), exist_ok=True)

        from conda_forge_tick.lazy_json_backends import (
            dumps,
            lazy_json_override_backends,
        )
        from conda_forge_tick.os_utils import pushd
        from conda_forge_tick.utils import setup_logging

        data = None
        ret = copy.copy(kwargs)
        try:
            with (
                redirect_stdout(sys.stderr),
                tempfile.TemporaryDirectory() as tmpdir,
                pushd(tmpdir),
            ):
                # logger call needs to be here so it gets the changed stdout/stderr
                setup_logging(log_level)
                if existing_feedstock_node_attrs is not None:
                    attrs = _get_existing_feedstock_node_attrs(
                        existing_feedstock_node_attrs
                    )
                    with lazy_json_override_backends(["github"], use_file_cache=False):
                        data = func(attrs=attrs, **kwargs)
                else:
                    with lazy_json_override_backends(["github"], use_file_cache=False):
                        data = func(**kwargs)

            ret["data"] = data

        except Exception as e:
            ret["data"] = data
            ret["error"] = repr(e)
            ret["traceback"] = traceback.format_exc()

        print(dumps(ret))


def _provide_source_code():
    from conda_forge_feedstock_ops.os_utils import chmod_plus_rwX, sync_dirs

    from conda_forge_tick.provide_source_code import provide_source_code_local

    logger = logging.getLogger("conda_forge_tick.container")

    with tempfile.TemporaryDirectory() as tmpdir:
        input_recipe_dir = "/cf_feedstock_ops_dir/recipe_dir"
        logger.debug(
            "input container recipe dir %s: %s",
            input_recipe_dir,
            os.listdir(input_recipe_dir),
        )

        recipe_dir = os.path.join(tmpdir, os.path.basename(input_recipe_dir))
        sync_dirs(input_recipe_dir, recipe_dir, ignore_dot_git=True, update_git=False)
        logger.debug(
            "copied container recipe dir %s: %s", recipe_dir, os.listdir(recipe_dir)
        )

        output_source_code = "/cf_feedstock_ops_dir/source_dir"
        os.makedirs(output_source_code, exist_ok=True)

        with provide_source_code_local(recipe_dir) as cb_work_dir:
            chmod_plus_rwX(cb_work_dir, recursive=True, skip_on_error=True)
            sync_dirs(
                cb_work_dir, output_source_code, ignore_dot_git=True, update_git=False
            )
            chmod_plus_rwX(output_source_code, recursive=True, skip_on_error=True)

        return dict()


def _execute_git_cmds_and_report(*, cmds, cwd, msg):
    logger = logging.getLogger("conda_forge_tick.container")

    try:
        _output = ""
        for cmd in cmds:
            gitret = subprocess.run(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            logger.debug("git command %r output: %s", cmd, gitret.stdout)
            _output += gitret.stdout
            gitret.check_returncode()
    except Exception as e:
        logger.error("%s\noutput: %s", msg, _output, exc_info=e)
        raise e


def _migrate_feedstock(*, feedstock_name, default_branch, attrs, input_kwargs):
    from conda_forge_feedstock_ops.os_utils import (
        chmod_plus_rwX,
        get_user_execute_permissions,
        reset_permissions_with_user_execute,
        sync_dirs,
    )

    from conda_forge_tick.lazy_json_backends import loads
    from conda_forge_tick.migration_runner import run_migration_local
    from conda_forge_tick.migrators import make_from_lazy_json_data

    logger = logging.getLogger("conda_forge_tick.container")

    with tempfile.TemporaryDirectory() as tmpdir:
        input_fs_dir_list = glob.glob("/cf_feedstock_ops_dir/*-feedstock")
        assert len(input_fs_dir_list) == 1, (
            f"expected one feedstock, got {input_fs_dir_list}"
        )
        input_fs_dir = input_fs_dir_list[0]
        logger.debug(
            "input container feedstock dir %s: %s",
            input_fs_dir,
            os.listdir(input_fs_dir),
        )
        input_permissions = os.path.join(
            "/cf_feedstock_ops_dir",
            f"permissions-{os.path.basename(input_fs_dir)}.json",
        )
        with open(input_permissions, "rb") as f:
            input_permissions = orjson.loads(f.read())

        fs_dir = os.path.join(tmpdir, os.path.basename(input_fs_dir))
        sync_dirs(input_fs_dir, fs_dir, ignore_dot_git=True, update_git=False)
        logger.debug(
            "copied container feedstock dir %s: %s", fs_dir, os.listdir(fs_dir)
        )

        reset_permissions_with_user_execute(fs_dir, input_permissions)

        with open("/cf_feedstock_ops_dir/migrator.json") as f:
            migrator = make_from_lazy_json_data(loads(f.read()))

        kwargs = loads(input_kwargs) if input_kwargs else {}
        data = run_migration_local(
            migrator=migrator,
            feedstock_dir=fs_dir,
            feedstock_name=feedstock_name,
            default_branch=default_branch,
            node_attrs=attrs,
            **kwargs,
        )

        data["permissions"] = get_user_execute_permissions(fs_dir)
        sync_dirs(fs_dir, input_fs_dir, ignore_dot_git=True, update_git=False)
        chmod_plus_rwX(input_fs_dir, recursive=True, skip_on_error=True)

    return data


def _update_version(*, version, hash_type):
    from conda_forge_feedstock_ops.os_utils import (
        chmod_plus_rwX,
        get_user_execute_permissions,
        reset_permissions_with_user_execute,
        sync_dirs,
    )

    from conda_forge_tick.update_recipe.version import (
        _update_version_feedstock_dir_local,
    )

    logger = logging.getLogger("conda_forge_tick.container")

    with tempfile.TemporaryDirectory() as tmpdir:
        input_fs_dir_list = glob.glob("/cf_feedstock_ops_dir/*-feedstock")
        assert len(input_fs_dir_list) == 1, (
            f"expected one feedstock, got {input_fs_dir_list}"
        )
        input_fs_dir = input_fs_dir_list[0]
        logger.debug(
            "input container feedstock dir %s: %s",
            input_fs_dir,
            os.listdir(input_fs_dir),
        )
        input_permissions = os.path.join(
            "/cf_feedstock_ops_dir",
            f"permissions-{os.path.basename(input_fs_dir)}.json",
        )
        with open(input_permissions, "rb") as f:
            input_permissions = orjson.loads(f.read())

        fs_dir = os.path.join(tmpdir, os.path.basename(input_fs_dir))
        sync_dirs(input_fs_dir, fs_dir, ignore_dot_git=True, update_git=False)
        logger.debug(
            "copied container feedstock dir %s: %s", fs_dir, os.listdir(fs_dir)
        )

        reset_permissions_with_user_execute(fs_dir, input_permissions)

        updated, errors = _update_version_feedstock_dir_local(
            fs_dir,
            version,
            hash_type,
        )
        data = {"updated": updated, "errors": errors}

        data["permissions"] = get_user_execute_permissions(fs_dir)
        sync_dirs(fs_dir, input_fs_dir, ignore_dot_git=True, update_git=False)
        chmod_plus_rwX(input_fs_dir, recursive=True, skip_on_error=True)

    return data


def _get_latest_version(*, attrs, sources):
    from conda_forge_tick.update_upstream_versions import (
        all_version_sources,
        get_latest_version_local,
    )

    _sources = all_version_sources()
    if sources is not None:
        sources = sources.split(",")
        sources = [s.strip().lower() for s in sources]
        _sources = [s for s in _sources if s.name.strip().lower() in sources]

    name = attrs["feedstock_name"]

    data = get_latest_version_local(
        name,
        attrs,
        _sources,
    )
    return data


def _parse_feedstock(
    *,
    attrs,
    meta_yaml,
    recipe_yaml,
    conda_forge_yaml,
    mark_not_archived,
):
    from conda_forge_tick.feedstock_parser import load_feedstock_local

    name = attrs["feedstock_name"]

    node_attrs = load_feedstock_local(
        name,
        attrs,
        meta_yaml=meta_yaml,
        recipe_yaml=recipe_yaml,
        conda_forge_yaml=conda_forge_yaml,
        mark_not_archived=mark_not_archived,
    )

    return node_attrs


def _parse_meta_yaml(
    *,
    for_pinning,
    platform,
    arch,
    cbc_path,
    orig_cbc_path,
    log_debug,
):
    from conda_forge_tick.utils import parse_meta_yaml_local

    return parse_meta_yaml_local(
        sys.stdin.read(),
        for_pinning=for_pinning,
        platform=platform,
        arch=arch,
        cbc_path=cbc_path,
        orig_cbc_path=orig_cbc_path,
        log_debug=log_debug,
    )


def _parse_recipe_yaml(
    *,
    for_pinning,
    platform_arch,
    cbc_path,
):
    from conda_forge_tick.utils import parse_recipe_yaml_local

    return parse_recipe_yaml_local(
        sys.stdin.read(),
        for_pinning=for_pinning,
        platform_arch=platform_arch,
        cbc_path=cbc_path,
    )


def _check_solvable(
    *,
    timeout,
    verbosity,
    additional_channels,
    build_platform,
):
    from conda_forge_tick.solver_checks import is_recipe_solvable

    logger = logging.getLogger("conda_forge_tick.container")

    logger.debug(
        "input container feedstock dir /cf_feedstock_ops_dir: %s",
        os.listdir("/cf_feedstock_ops_dir"),
    )

    data = {}
    data["solvable"], data["errors"], data["solvable_by_variant"] = is_recipe_solvable(
        "/cf_feedstock_ops_dir",
        use_container=False,
        timeout=timeout,
        verbosity=verbosity,
        additional_channels=(
            additional_channels.split(",") if additional_channels else None
        ),
        build_platform=orjson.loads(build_platform) if build_platform else None,
    )
    return data


@click.group()
def cli():
    pass


@cli.command(name="parse-meta-yaml")
@log_level_option
@click.option(
    "--for-pinning",
    is_flag=True,
    help="Parse the meta.yaml for pinning requirements.",
)
@click.option(
    "--platform",
    type=str,
    default=None,
    help="The platform (e.g., 'linux', 'osx', 'win').",
)
@click.option(
    "--arch",
    type=str,
    default=None,
    help="The CPU architecture (e.g., '64', 'aarch64').",
)
@click.option(
    "--cbc-path", type=str, default=None, help="The path to global pinning file."
)
@click.option(
    "--orig-cbc-path",
    type=str,
    default=None,
    help="The path to the original global pinning file.",
)
@click.option("--log-debug", is_flag=True, help="Log debug information.")
def parse_meta_yaml(
    log_level: str,
    for_pinning,
    platform,
    arch,
    cbc_path,
    orig_cbc_path,
    log_debug,
):
    return _run_bot_task(
        _parse_meta_yaml,
        log_level=log_level,
        existing_feedstock_node_attrs=None,
        for_pinning=for_pinning,
        platform=platform,
        arch=arch,
        cbc_path=cbc_path,
        orig_cbc_path=orig_cbc_path,
        log_debug=log_debug,
    )


@cli.command(name="parse-recipe-yaml")
@log_level_option
@click.option(
    "--for-pinning",
    is_flag=True,
    help="Parse the recipe.yaml for pinning requirements.",
)
@click.option(
    "--platform-arch",
    type=str,
    default=None,
    help="The platform and arch (e.g., 'linux-64', 'osx-arm64', 'win-64').",
)
@click.option(
    "--cbc-path", type=str, default=None, help="The path to global pinning file."
)
def parse_recipe_yaml(
    log_level: str,
    for_pinning,
    platform_arch,
    cbc_path,
):
    return _run_bot_task(
        _parse_recipe_yaml,
        log_level=log_level,
        existing_feedstock_node_attrs=None,
        for_pinning=for_pinning,
        platform_arch=platform_arch,
        cbc_path=cbc_path,
    )


@cli.command(name="parse-feedstock")
@log_level_option
@existing_feedstock_node_attrs_option
@click.option("--meta-yaml", default=None, type=str, help="The meta.yaml file to use.")
@click.option(
    "--recipe-yaml", default=None, type=str, help="The recipe.yaml file to use."
)
@click.option(
    "--conda-forge-yaml", default=None, type=str, help="The meta.yaml file to use."
)
@click.option(
    "--mark-not-archived", is_flag=True, help="Mark the feedstock as not archived."
)
def parse_feedstock(
    log_level,
    existing_feedstock_node_attrs,
    meta_yaml,
    recipe_yaml,
    conda_forge_yaml,
    mark_not_archived,
):
    return _run_bot_task(
        _parse_feedstock,
        log_level=log_level,
        existing_feedstock_node_attrs=existing_feedstock_node_attrs,
        meta_yaml=meta_yaml,
        recipe_yaml=recipe_yaml,
        conda_forge_yaml=conda_forge_yaml,
        mark_not_archived=mark_not_archived,
    )


@cli.command(name="get-latest-version")
@log_level_option
@existing_feedstock_node_attrs_option
@click.option(
    "--sources",
    default=None,
    type=str,
    help="Comma separated list of sources to use. Default is all sources as given by `all_version_sources`.",
)
def get_latest_version(log_level, existing_feedstock_node_attrs, sources):
    return _run_bot_task(
        _get_latest_version,
        log_level=log_level,
        existing_feedstock_node_attrs=existing_feedstock_node_attrs,
        sources=sources,
    )


@cli.command(name="migrate-feedstock")
@log_level_option
@existing_feedstock_node_attrs_option
@click.option(
    "--feedstock-name", type=str, required=True, help="The name of the feedstock."
)
@click.option(
    "--default-branch",
    type=str,
    required=True,
    help="The default branch of the feedstock.",
)
@click.option(
    "--kwargs",
    type=str,
    default=None,
    help="The input kwargs JSON as a string.",
)
def migrate_feedstock(
    log_level, existing_feedstock_node_attrs, feedstock_name, default_branch, kwargs
):
    return _run_bot_task(
        _migrate_feedstock,
        log_level=log_level,
        existing_feedstock_node_attrs=existing_feedstock_node_attrs,
        feedstock_name=feedstock_name,
        default_branch=default_branch,
        input_kwargs=kwargs,
    )


@cli.command(name="provide-source-code")
@log_level_option
def provide_source_code(log_level):
    return _run_bot_task(
        _provide_source_code,
        log_level=log_level,
        existing_feedstock_node_attrs=None,
    )


@cli.command(name="check-solvable")
@log_level_option
@click.option(
    "--timeout",
    type=int,
    default=600,
    help="The timeout for the solver check in seconds.",
)
@click.option(
    "--verbosity",
    type=int,
    default=1,
    help="The verbosity of the solver check. 0 is no output, 3 is a lot of output.",
)
@click.option(
    "--additional-channels",
    type=str,
    default=None,
    help="Additional channels to use for the solver check as a comma separated list.",
)
@click.option(
    "--build-platform",
    type=str,
    default=None,
    help="The conda-forge.yml build_platform section as a JSON string.",
)
def check_solvable(log_level, timeout, verbosity, additional_channels, build_platform):
    return _run_bot_task(
        _check_solvable,
        log_level=log_level,
        existing_feedstock_node_attrs=None,
        timeout=timeout,
        verbosity=verbosity,
        additional_channels=additional_channels,
        build_platform=build_platform,
    )


@cli.command(name="update-version")
@log_level_option
@click.option("--version", type=str, required=True, help="The version to update to.")
@click.option(
    "--hash-type",
    type=str,
    required=True,
    help="The type of hash to use.",
)
def update_version(
    log_level,
    version,
    hash_type,
):
    return _run_bot_task(
        _update_version,
        log_level=log_level,
        existing_feedstock_node_attrs=None,
        version=version,
        hash_type=hash_type,
    )


if __name__ == "__main__":
    cli()
