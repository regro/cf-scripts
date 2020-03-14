import os
import re
import builtins
import logging
import datetime
from unittest import mock

import pytest
import networkx as nx

from conda_forge_tick.contexts import MigratorSessionContext, MigratorContext
from conda_forge_tick.utils import parse_meta_yaml, frozen_to_json_friendly
from conda_forge_tick.make_graph import populate_feedstock_attributes
from conda_forge_tick.migrators import MigrationYamlCreator
from conda_forge_tick.xonsh_utils import eval_xonsh, indir

G = nx.DiGraph()
G.add_node("conda", reqs=["python"])
env = builtins.__xonsh__.env  # type: ignore
env["GRAPH"] = G
env["CIRCLE_BUILD_URL"] = "hi world"


IN_YAML = """\
{% set version = "2020.03.10" %}

package:
  name: conda-forge-pinning
  version: {{ version }}

source:
  path: .

build:
  number: 0
  noarch: generic
  script:
    - cp conda_build_config.yaml $PREFIX                       # [unix]
    - mkdir -p $PREFIX/share/conda-forge/migrations            # [unix]
    - cp migrations/* $PREFIX/share/conda-forge/migrations/    # [unix]
    - echo "This package can't be built on windows"            # [win]
    - exit 1                                                   # [win]
"""


OUT_YAML = """\
{%% set version = "%s" %%}

package:
  name: conda-forge-pinning
  version: {{ version }}

source:
  path: .

build:
  number: 0
  noarch: generic
  script:
    - cp conda_build_config.yaml $PREFIX                       # [unix]
    - mkdir -p $PREFIX/share/conda-forge/migrations            # [unix]
    - cp migrations/* $PREFIX/share/conda-forge/migrations/    # [unix]
    - echo "This package can't be built on windows"            # [win]
    - exit 1                                                   # [win]
""" % datetime.datetime.now().strftime("%Y.%m.%d")


IN_YAML_TODAY = """\
{%% set version = "%s" %%}

package:
  name: conda-forge-pinning
  version: {{ version }}

source:
  path: .

build:
  number: 0
  noarch: generic
  script:
    - cp conda_build_config.yaml $PREFIX                       # [unix]
    - mkdir -p $PREFIX/share/conda-forge/migrations            # [unix]
    - cp migrations/* $PREFIX/share/conda-forge/migrations/    # [unix]
    - echo "This package can't be built on windows"            # [win]
    - exit 1                                                   # [win]
""" % datetime.datetime.now().strftime("%Y.%m.%d")


OUT_YAML_TODAY = """\
{%% set version = "%s" %%}

package:
  name: conda-forge-pinning
  version: {{ version }}

source:
  path: .

build:
  number: 1
  noarch: generic
  script:
    - cp conda_build_config.yaml $PREFIX                       # [unix]
    - mkdir -p $PREFIX/share/conda-forge/migrations            # [unix]
    - cp migrations/* $PREFIX/share/conda-forge/migrations/    # [unix]
    - echo "This package can't be built on windows"            # [win]
    - exit 1                                                   # [win]
""" % datetime.datetime.now().strftime("%Y.%m.%d")

BOOST_YAML = """\
__migrator:
  build_number: 1
  kind: version
  migration_number: 1
boost:
- 1.99.0
migrator_ts: '12345.2'
"""


@pytest.mark.parametrize("in_out_yaml", [
    (IN_YAML, OUT_YAML),
    (IN_YAML_TODAY, OUT_YAML_TODAY),
])
@mock.patch("time.time")
def test_migration_yaml_migration(tmock, in_out_yaml, caplog, tmpdir):
    caplog.set_level(
        logging.DEBUG,
        logger='conda_forge_tick.migrators.migration_yaml',
    )
    tmock.return_value = 12345.2
    pname = "boost"
    pin_ver = "1.99.0"
    curr_pin = "1.70.0"
    pin_spec = "blah"

    MYM = MigrationYamlCreator(
        pname,
        pin_ver,
        curr_pin,
        pin_spec,
    )

    with indir(tmpdir):
        eval_xonsh("git init .")

    os.makedirs(os.path.join(tmpdir, "migrations"), exist_ok=True)

    run_test_migration(
        m=MYM,
        inp=in_out_yaml[0],
        output=in_out_yaml[1],
        kwargs={},
        prb="This PR has been triggered in an effort to update the pin",
        mr_out={
            "migrator_name": "MigrationYamlCreator",
            "migrator_version": MYM.migrator_version,
            "name": pname,
            "pin_version": pin_ver,
        },
        tmpdir=tmpdir,
    )

    boost_file = os.path.join(tmpdir, "migrations", "boost1990.yaml")
    assert os.path.exists(boost_file)
    with open(boost_file, "r") as fp:
        bf_out = fp.read()
    assert BOOST_YAML == bf_out


def run_test_migration(
    m, inp, output, kwargs, prb, mr_out, should_filter=False, tmpdir=None,
):
    mm_ctx = MigratorSessionContext(
        graph=G,
        smithy_version="",
        pinning_version="",
        github_username="",
        github_password="",
        circle_build_url=env["CIRCLE_BUILD_URL"],
    )
    m_ctx = MigratorContext(mm_ctx, m)
    m.bind_to_ctx(m_ctx)

    if mr_out:
        mr_out.update(bot_rerun=False)
    with open(os.path.join(tmpdir, "meta.yaml"), "w") as f:
        f.write(inp)

    # read the conda-forge.yml
    if os.path.exists(os.path.join(tmpdir, '..', 'conda-forge.yml')):
        with open(os.path.join(tmpdir, '..', 'conda-forge.yml'), 'r') as fp:
            cf_yml = fp.read()
    else:
        cf_yml = "{}"

    # Load the meta.yaml (this is done in the graph)
    try:
        name = parse_meta_yaml(inp)['package']['name']
    except Exception:
        name = 'blah'

    pmy = populate_feedstock_attributes(
        name,
        {},
        inp,
        cf_yml,
    )

    # these are here for legacy migrators
    pmy["version"] = pmy['meta_yaml']["package"]["version"]
    pmy["req"] = set()
    for k in ["build", "host", "run"]:
        req = pmy['meta_yaml'].get("requirements", {}) or {}
        _set = req.get(k) or set()
        pmy["req"] |= set(_set)
    pmy["raw_meta_yaml"] = inp
    pmy.update(kwargs)

    assert m.filter(pmy) is should_filter
    if should_filter:
        return

    m.run_pre_piggyback_migrations(
        tmpdir, pmy, hash_type=pmy.get("hash_type", "sha256"))
    mr = m.migrate(tmpdir, pmy, hash_type=pmy.get("hash_type", "sha256"))
    m.run_post_piggyback_migrations(
        tmpdir, pmy, hash_type=pmy.get("hash_type", "sha256"))

    assert mr_out == mr
    if not mr:
        return

    pmy.update(PRed=[frozen_to_json_friendly(mr)])
    with open(os.path.join(tmpdir, "meta.yaml"), "r") as f:
        actual_output = f.read()
    # strip jinja comments
    pat = re.compile(r"{#.*#}")
    actual_output = pat.sub("", actual_output)
    output = pat.sub("", output)
    assert actual_output == output
