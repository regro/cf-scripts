import os

import pytest

from test_migrators import run_test_migration, run_minimigrator


from conda_forge_tick.migrators import (
    Version,
    PipWheelMigrator,
)

wheel_mig = PipWheelMigrator()

version_migrator_whl = Version(
    set(),
    piggy_back_migrations=[wheel_mig],
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

extra:
  bot:
    run_deps_from_wheel: true
"""

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
    - opentelemetry-api =1.4.1
    # - wrapt <2.0.0,>=1.0.0

about:
  license: Apache-2.0
  license_file: LICENSE.txt

extra:
  bot:
    run_deps_from_wheel: true
"""


def test_migrate_opentelemetry(tmpdir):
    run_test_migration(
        m=version_migrator_whl,
        inp=opentelemetry_instrumentation,
        output=opentelemetry_instrumentation_expected,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "0.23b2"},
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "0.23b2",
        },
        tmpdir=tmpdir,
    )


@pytest.mark.parametrize("package", ["icu", "pipcheck_simple"])
def test_migrate_non_python(tmpdir, package):
    """Shouldn't run for non-python recipes or recipes that
    have not opted in to the wheel migrator.
    """
    with open(os.path.join(YAML_PATH, f"version_{package}.yaml")) as fp:
        in_yaml = fp.read()

    run_minimigrator(
        migrator=wheel_mig,
        inp=in_yaml,
        output="",
        mr_out=None,
        should_filter=True,
        tmpdir=tmpdir,
    )


def test_migrate_thrift(tmpdir):
    """Packages without a wheel should be filtered out"""
    import requests

    url = "https://raw.githubusercontent.com/conda-forge/thrift-feedstock/e0327f2a8b75151428e22c722b311a4ac9fccf41/recipe/meta.yaml"
    in_yaml = requests.get(url).text
    in_yaml += """\
  bot:
    run_deps_from_wheel: true
"""

    run_minimigrator(
        migrator=wheel_mig,
        inp=in_yaml,
        output="",
        mr_out=None,
        should_filter=True,
        tmpdir=tmpdir,
    )


def test_migrate_psutil(tmpdir):
    """Packages with many wheels should be filtered out"""
    import requests

    url = "https://raw.githubusercontent.com/conda-forge/psutil-feedstock/0cfe57ff0dd639ed872e6e1d220a297ddc3b9100/recipe/meta.yaml"
    in_yaml = requests.get(url).text
    in_yaml += """\
  bot:
    run_deps_from_wheel: true
"""

    run_minimigrator(
        migrator=wheel_mig,
        inp=in_yaml,
        output="",
        mr_out=None,
        should_filter=True,
        tmpdir=tmpdir,
    )
