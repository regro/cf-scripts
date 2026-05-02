import logging
import os
import re
from unittest import mock

import pytest

from conda_forge_tick.feedstock_parser import populate_feedstock_attributes
from conda_forge_tick.migrators import MigrationYamlCreator, merge_migrator_cbc
from conda_forge_tick.os_utils import eval_cmd, pushd
from conda_forge_tick.utils import frozen_to_json_friendly, parse_meta_yaml

os.environ["RUN_URL"] = "hi world"

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")

IN_YAML = """\
{% set version = datetime.datetime.utcnow().strftime("%Y.%m.%d.%H.%M.%S") %}

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
{% set version = datetime.datetime.utcnow().strftime("%Y.%m.%d.%H.%M.%S") %}

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


IN_YAML_TODAY = """\
{% set version = datetime.datetime.utcnow().strftime("%Y.%m.%d.%H.%M.%S") %}

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


OUT_YAML_TODAY = """\
{% set version = datetime.datetime.utcnow().strftime("%Y.%m.%d.%H.%M.%S") %}

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

BOOST_YAML = """\
__migrator:
  build_number: 1
  commit_message: Rebuild for libboost_devel 1.99
  kind: version
  migration_number: 1
libboost_devel:
- '1.99'
libboost_python_devel:
- '1.99'
migrator_ts: 12345.2
"""


@pytest.mark.parametrize(
    "in_out_yaml",
    [(IN_YAML, OUT_YAML), (IN_YAML_TODAY, OUT_YAML_TODAY)],
)
@mock.patch("time.time")
def test_migration_yaml_migration(tmock, in_out_yaml, caplog, tmp_path, test_graph):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.migration_yaml",
    )
    tmock.return_value = 12345.2
    pname = "libboost_devel"
    pin_ver = "1.99.0"
    curr_pin = "1.70.0"
    pin_spec = "x.x"

    MYM = MigrationYamlCreator(
        package_name=pname,
        new_pin_version=pin_ver,
        current_pin=curr_pin,
        pin_spec=pin_spec,
        feedstock_name="hi",
        pinnings=["libboost_devel", "libboost_python_devel"],
        total_graph=test_graph,
    )

    with pushd(tmp_path):
        eval_cmd(["git", "init", "."])

    tmp_path.joinpath("recipe/migrations").mkdir(parents=True)

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
            "pin_version": "1.99",
        },
        tmp_path=tmp_path,
    )

    boost_file = tmp_path / "recipe/migrations/libboost_devel199.yaml"
    assert boost_file.exists()
    with open(boost_file) as fp:
        bf_out = fp.read()
    assert BOOST_YAML == bf_out


def run_test_migration(
    m,
    inp,
    output,
    kwargs,
    prb,
    mr_out,
    should_filter=False,
    tmp_path=None,
):
    if mr_out:
        mr_out.update(bot_rerun=False)
    recipe_path = tmp_path / "recipe"
    recipe_path.mkdir(exist_ok=True)
    with open(recipe_path / "meta.yaml", "w") as f:
        f.write(inp)

    # read the conda-forge.yml
    if os.path.exists(tmp_path / "conda-forge.yml"):
        with open(tmp_path / "conda-forge.yml") as fp:
            cf_yml = fp.read()
    else:
        cf_yml = "{}"

    # Load the meta.yaml (this is done in the graph)
    try:
        name = parse_meta_yaml(inp)["package"]["name"]
    except Exception:
        name = "blah"

    pmy = populate_feedstock_attributes(name, {}, inp, None, cf_yml)

    # these are here for legacy migrators
    pmy["version"] = pmy["meta_yaml"]["package"]["version"]
    pmy["req"] = set()
    for k in ["build", "host", "run"]:
        req = pmy["meta_yaml"].get("requirements", {}) or {}
        _set = req.get(k) or set()
        pmy["req"] |= set(_set)
    pmy["raw_meta_yaml"] = inp
    pmy.update(kwargs)

    assert m.filter(pmy) is should_filter
    if should_filter:
        return

    recipe_dir = str(recipe_path)
    m.run_pre_piggyback_migrations(
        recipe_dir,
        pmy,
        hash_type=pmy.get("hash_type", "sha256"),
    )
    mr = m.migrate(recipe_dir, pmy, hash_type=pmy.get("hash_type", "sha256"))
    m.run_post_piggyback_migrations(
        recipe_dir,
        pmy,
        hash_type=pmy.get("hash_type", "sha256"),
    )

    assert mr_out == mr
    if not mr:
        return

    pmy["pr_info"] = {}
    pmy["pr_info"].update(PRed=[frozen_to_json_friendly(mr)])
    with open(recipe_path / "meta.yaml") as f:
        actual_output = f.read()
    # strip jinja comments
    pat = re.compile(r"{#.*#}")
    actual_output = pat.sub("", actual_output)
    output = pat.sub("", output)
    assert actual_output == output


with open(os.path.join(YAML_PATH, "conda_build_config.yaml")) as fp:
    CBC = fp.read()


@pytest.mark.parametrize("migrator_name", ["pypy", "krb", "boost"])
def test_merge_migrator_cbc(migrator_name):
    with open(os.path.join(YAML_PATH, f"{migrator_name}.yaml")) as fp:
        migrator = fp.read()
    with open(os.path.join(YAML_PATH, f"{migrator_name}_out.yaml")) as fp:
        out = fp.read()
    assert merge_migrator_cbc(migrator, CBC) == out
