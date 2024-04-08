#!/usr/bin/env python
import os
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import click

from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    dumps,
    lazy_json_override_backends,
    load,
    loads,
)
from conda_forge_tick.update_upstream_versions import (
    all_version_sources,
    get_latest_version,
)

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


def _handle_existing_feedstock_node_attrs(existing_feedstock_node_attrs):
    if existing_feedstock_node_attrs.startswith("{"):
        data = loads(existing_feedstock_node_attrs)
        pth = data["feedstock_name"] + ".json"
        with open(pth, "w") as fp:
            fp.write(existing_feedstock_node_attrs)
        return pth
    else:
        if not existing_feedstock_node_attrs.endswith(".json"):
            existing_feedstock_node_attrs += ".json"
        pth = os.path.join("node_attrs", existing_feedstock_node_attrs)
        with lazy_json_override_backends(["github"], use_file_cache=False), LazyJson(
            pth
        ) as lzj, open(existing_feedstock_node_attrs, "w") as fp:
            fp.write(dumps(lzj.data))

        return existing_feedstock_node_attrs


@click.group()
def cli():
    pass


@cli.command(name="update-version")
@existing_feedstock_node_attrs_option
def update_version(existing_feedstock_node_attrs):
    node_attrs_file = _handle_existing_feedstock_node_attrs(
        existing_feedstock_node_attrs
    )

    name = os.path.basename(node_attrs_file)[: -len(".json")]
    with open(node_attrs_file) as fp:
        attrs = load(fp)

    outerr = StringIO()
    with redirect_stdout(outerr), redirect_stderr(outerr):
        data = get_latest_version(
            name,
            attrs,
            all_version_sources(),
        )

    print(dumps(data))


if __name__ == "__main__":
    cli()
