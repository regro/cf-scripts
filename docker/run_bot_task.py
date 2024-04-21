#!/usr/bin/env python
"""This file runs specific tasks for the bot.

All imports from the bot need to be guarded by putting them in the subcommands.
This ensures that we can set important environment variables before any imports,
including `CONDA_BLD_PATH`.

This container is run in a read-only environment except a small tmpfs volume
mounted at `/tmp`. The `TMPDIR` environment variable is set to `/tmp` so that
one can use the `tempfile` module to create temporary files and directories.

These tasks return their info to the bot by printing a JSON blob to stdout.
"""

import copy
import logging
import os
import sys
import tempfile
import traceback
from contextlib import contextmanager, redirect_stdout
from io import StringIO

import click

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
    """set an environment variable temporarily"""
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


def _run_bot_task(func, *, log_level, existing_feedstock_node_attrs, **kwargs):
    with (
        tempfile.TemporaryDirectory() as tmpdir_cbld,
        _setenv("CONDA_BLD_PATH", os.path.join(tmpdir_cbld, "conda-bld")),
        tempfile.TemporaryDirectory() as tmpdir_cache,
        _setenv("XDG_CACHE_HOME", tmpdir_cache),
    ):
        os.makedirs(os.path.join(tmpdir_cbld, "conda-bld"), exist_ok=True)

        from conda_forge_tick.lazy_json_backends import dumps
        from conda_forge_tick.os_utils import pushd
        from conda_forge_tick.utils import setup_logging

        data = None
        ret = copy.copy(kwargs)
        stdout = StringIO()
        try:
            with (
                redirect_stdout(stdout),
                tempfile.TemporaryDirectory() as tmpdir,
                pushd(tmpdir),
            ):
                # logger call needs to be here so it gets the changed stdout/stderr
                setup_logging(log_level)
                if existing_feedstock_node_attrs is not None:
                    attrs = _get_existing_feedstock_node_attrs(
                        existing_feedstock_node_attrs
                    )
                    data = func(attrs=attrs, **kwargs)
                else:
                    data = func(**kwargs)

            ret["data"] = data
            ret["container_stdout"] = stdout.getvalue()

        except Exception as e:
            ret["data"] = data
            ret["container_stdout"] = stdout.getvalue()
            ret["error"] = repr(e)
            ret["traceback"] = traceback.format_exc()

        print(dumps(ret))


def _provide_source_code():
    from conda_forge_tick.os_utils import sync_dirs, chmod_plus_rwX
    from conda_forge_tick.provide_source_code import provide_source_code_local

    logger = logging.getLogger("conda_forge_tick.container")

    with tempfile.TemporaryDirectory() as tmpdir:
        input_recipe_dir = "/cf_tick_dir/recipe_dir"
        logger.info(
            f"input container recipe dir {input_recipe_dir}: {os.listdir(input_recipe_dir)}"
        )

        recipe_dir = os.path.join(tmpdir, os.path.basename(input_recipe_dir))
        sync_dirs(input_recipe_dir, recipe_dir, ignore_dot_git=True, update_git=False)
        logger.info(f"copied container feedstock dir {recipe_dir}: {os.listdir(recipe_dir)}")

        output_source_code = "/cf_tick_dir/source_code"
        os.makedirs(output_source_code, exist_ok=True)

        with provide_source_code_local(recipe_dir) as cb_work_dir:
            sync_dirs(cb_work_dir, output_source_code, ignore_dot_git=True, update_git=False)
            chmod_plus_rwX(output_source_code)

        return None


def _rerender_feedstock(*, timeout):
    import glob
    import subprocess

    from conda_forge_tick.os_utils import sync_dirs
    from conda_forge_tick.rerender_feedstock import rerender_feedstock_local

    logger = logging.getLogger("conda_forge_tick.container")

    with tempfile.TemporaryDirectory() as tmpdir:
        input_fs_dir = glob.glob("/cf_tick_dir/*-feedstock")
        assert len(input_fs_dir) == 1, f"expected one feedstock, got {input_fs_dir}"
        input_fs_dir = input_fs_dir[0]
        logger.info(
            f"input container feedstock dir {input_fs_dir}: {os.listdir(input_fs_dir)}"
        )

        fs_dir = os.path.join(tmpdir, os.path.basename(input_fs_dir))
        sync_dirs(input_fs_dir, fs_dir, ignore_dot_git=True, update_git=False)
        if os.path.exists(os.path.join(fs_dir, ".gitignore")):
            os.remove(os.path.join(fs_dir, ".gitignore"))
        logger.info(f"copied container feedstock dir {fs_dir}: {os.listdir(fs_dir)}")

        cmds = [
            ["git", "init", "-b", "main", "."],
            ["git", "add", "."],
            ["git", "commit", "-am", "initial commit"],
        ]
        for cmd in cmds:
            subprocess.run(
                cmd,
                check=True,
                cwd=fs_dir,
                stdout=sys.stderr,
            )

        if timeout is not None:
            kwargs = {"timeout": timeout}
        else:
            kwargs = {}
        msg = rerender_feedstock_local(fs_dir, **kwargs)

        # if something changed, copy back the new feedstock
        if msg is not None:
            sync_dirs(fs_dir, input_fs_dir, ignore_dot_git=True, update_git=False)

        return {"commit_message": msg}


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
    conda_forge_yaml,
    mark_not_archived,
):
    from conda_forge_tick.feedstock_parser import load_feedstock_local

    name = attrs["feedstock_name"]

    load_feedstock_local(
        name,
        attrs,
        meta_yaml=meta_yaml,
        conda_forge_yaml=conda_forge_yaml,
        mark_not_archived=mark_not_archived,
    )

    return attrs


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
    "--orig_cbc_path",
    type=str,
    default=None,
    help="The path to the original global pinning file.",
)
@click.option("--log-debug", is_flag=True, help="Log debug information.")
def parse_meta_yaml(
    log_level,
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


@cli.command(name="parse-feedstock")
@log_level_option
@existing_feedstock_node_attrs_option
@click.option("--meta-yaml", default=None, type=str, help="The meta.yaml file to use.")
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
    conda_forge_yaml,
    mark_not_archived,
):
    return _run_bot_task(
        _parse_feedstock,
        log_level=log_level,
        existing_feedstock_node_attrs=existing_feedstock_node_attrs,
        meta_yaml=meta_yaml,
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


@cli.command(name="rerender-feedstock")
@log_level_option
@click.option("--timeout", default=None, type=int, help="The timeout for the rerender.")
def rerender_feedstock(log_level, timeout):
    return _run_bot_task(
        _rerender_feedstock,
        log_level=log_level,
        existing_feedstock_node_attrs=None,
        timeout=timeout,
    )


@cli.command(name="provide-source-code")
@log_level_option
def provide_source_code(log_level):
    return _run_bot_task(
        _provide_source_code,
        log_level=log_level,
        existing_feedstock_node_attrs=None,
    )


if __name__ == "__main__":
    cli()
