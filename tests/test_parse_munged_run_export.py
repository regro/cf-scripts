from conda_forge_tick.utils import parse_munged_run_export, parse_meta_yaml


RECIPE = """\
{% set version = "3.19.1" %}
{% set sha256 = "280737e9ef762d7f0079ad3ad29913215c799ebf124651c723c1972f71fbc0db" %}
{% set build = 0 %}

package:
  name: slepc
  version: {{ version }}

source:
  url: http://slepc.upv.es/download/distrib/slepc-{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  skip: true  # [win]
  number: {{ build }}
  string: real_h{{ PKG_HASH }}_{{ build }}
  run_exports:
    - {{ pin_subpackage('slepc', max_pin='x.x') }} real_*  # comment

requirements:
  run:
    - petsc
    - suitesparse

about:
  home: http://slepc.upv.es/
  summary: 'SLEPc: Scalable Library for Eigenvalue Problem Computations'
  license: BSD-2-Clause
  license_file: LICENSE.md
  license_family: BSD

extra:
  recipe-maintainers:
    - dalcinl
    - joseeroman
    - minrk

"""


def test_parse_munged_run_export():
    meta_yaml = parse_meta_yaml(
        RECIPE,
        for_pinning=True,
    )
    assert meta_yaml["build"]["run_exports"] == [
        "__dict__ 'package_name'@ 'slepc', 'max_pin'@ 'x.x' __dict__ real_*"
    ]
    assert parse_munged_run_export(
        meta_yaml["build"]["run_exports"][0]
    ) == {'package_name': 'slepc', 'max_pin': 'x.x'}
