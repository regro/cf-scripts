import os

import networkx as nx
import pytest
import requests
from test_migrators import run_minimigrator, run_test_migration

from conda_forge_tick.migrators import PipWheelMigrator, Version

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}

wheel_mig = PipWheelMigrator()

version_migrator_whl = Version(
    set(),
    piggy_back_migrations=[wheel_mig],
    total_graph=TOTAL_GRAPH,
)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")

opentelemetry_instrumentation = """\
{% set name = "opentelemetry-instrumentation" %}
{% set version = "0.22b0" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/opentelemetry-instrumentation-{{ version }}.tar.gz
  sha256: dummy_hash

build:
  number: 0
  noarch: python
  entry_points:
    - opentelemetry-instrument = opentelemetry.instrumentation.auto_instrumentation:run
    - opentelemetry-bootstrap = opentelemetry.instrumentation.bootstrap:run
  script: {{ PYTHON }} -m pip install . -vv

requirements:
  host:
    - pip
    - python >=3.5
  run:
    - python >=3.5
    - opentelemetry-api

about:
  license: Apache-2.0
  license_file: LICENSE.txt
"""  # noqa

opentelemetry_instrumentation_expected = """\
{% set name = "opentelemetry-instrumentation" %}
{% set version = "0.23b2" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/opentelemetry-instrumentation-{{ version }}.tar.gz
  sha256: 03f47469f47970e96d69ae65a231c3e3510b160ac19c90b09ab33893876e2b89

build:
  number: 0
  noarch: python
  entry_points:
    - opentelemetry-instrument = opentelemetry.instrumentation.auto_instrumentation:run
    - opentelemetry-bootstrap = opentelemetry.instrumentation.bootstrap:run
  script: {{ PYTHON }} -m pip install . -vv

requirements:
  host:
    - pip
    - python >=3.5
  run:
    - python >=3.5
    - opentelemetry-api ==1.4.1
    # - wrapt <2.0.0,>=1.0.0

about:
  license: Apache-2.0
  license_file: LICENSE.txt
"""  # noqa


@pytest.fixture()
def tmp_dir_with_conf(tmp_path):
    (tmp_path / "conda-forge.yml").write_text(
        """\
bot:
    run_deps_from_wheel: true
""",
    )
    return tmp_path


def test_migrate_opentelemetry(tmp_dir_with_conf):
    run_test_migration(
        m=version_migrator_whl,
        inp=opentelemetry_instrumentation,
        output=opentelemetry_instrumentation_expected,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "0.23b2"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.23b2",
        },
        tmp_path=tmp_dir_with_conf,
    )


@pytest.mark.parametrize("package", ["icu", "pipcheck_simple"])
def test_migrate_non_python(tmp_dir_with_conf, package):
    # the migrator shouldn't run for non-python recipes or recipes that
    # have not opted in to the wheel migrator.
    with open(os.path.join(YAML_PATH, f"version_{package}.yaml")) as fp:
        in_yaml = fp.read()

    run_minimigrator(
        migrator=wheel_mig,
        inp=in_yaml,
        output="",
        mr_out=None,
        should_filter=True,
        tmp_path=tmp_dir_with_conf,
    )


def test_migrate_thrift(tmp_dir_with_conf):
    """Packages without a wheel should be filtered out."""
    url = (
        "https://raw.githubusercontent.com/conda-forge/thrift-feedstock/"
        "e0327f2a8b75151428e22c722b311a4ac9fccf41/recipe/meta.yaml"
    )
    in_yaml = requests.get(url).text

    run_minimigrator(
        migrator=wheel_mig,
        inp=in_yaml,
        output="",
        mr_out=None,
        should_filter=True,
        tmp_path=tmp_dir_with_conf,
    )


def test_migrate_psutil(tmp_dir_with_conf):
    """Packages with many wheels should be filtered out."""
    url = (
        "https://raw.githubusercontent.com/conda-forge/psutil-feedstock/"
        "0cfe57ff0dd639ed872e6e1d220a297ddc3b9100/recipe/meta.yaml"
    )
    in_yaml = requests.get(url).text

    run_minimigrator(
        migrator=wheel_mig,
        inp=in_yaml,
        output="",
        mr_out=None,
        should_filter=True,
        tmp_path=tmp_dir_with_conf,
    )


def test_migrate_black(tmp_dir_with_conf):
    """Black has a wheel so this minimigrator should attempt to run."""
    url = (
        "https://raw.githubusercontent.com/conda-forge/black-feedstock/"
        "fc15d64cbd793b31a26cae5347dedcf42f562f1c/recipe/meta.yaml"
    )

    in_yaml = requests.get(url).text

    run_minimigrator(
        migrator=wheel_mig,
        inp=in_yaml,
        output=in_yaml,
        mr_out=None,
        should_filter=False,
        tmp_path=tmp_dir_with_conf,
    )


def test_migrate_black_no_conf(tmp_path):
    """Without enabling the feature, don't run for black."""
    url = (
        "https://raw.githubusercontent.com/conda-forge/black-feedstock/"
        "fc15d64cbd793b31a26cae5347dedcf42f562f1c/recipe/meta.yaml"
    )

    in_yaml = requests.get(url).text

    run_minimigrator(
        migrator=wheel_mig,
        inp=in_yaml,
        output=in_yaml,
        mr_out=None,
        should_filter=True,
        tmp_path=tmp_path,
    )
