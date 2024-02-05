import pytest

from conda_forge_tick.migrators.jinja2_vars_cleanup import (
    _cleanup_raw_yaml,
    _should_filter,
)


@pytest.mark.parametrize(
    "raw_yaml",
    [
        "{{name}}",
        "{{ name}}",
        "{{name }}",
        "{{name|lower}}",
        "{{ name|lower}}",
        "{{name|lower }}",
        "{{name[0]}}",
        "{{ name[0]}}",
        "{{name[0] }}",
        "{{name.replace('-', '_')}}",
        "{{ name.replace('-', '_')}}",
        "{{name.replace('-', '_') }}",
        "{{x.update({4:5})}}",
        "{{x.update({4:5}) }}",
        "{{ x.update({4:5})}}",
    ],
)
def test_jinja2_vars_cleanup_should_filter(raw_yaml):
    assert not _should_filter(raw_yaml)


@pytest.mark.parametrize(
    "raw_yaml,res",
    [
        ("{{name}}", "{{ name }}"),
        ("{{ name}}", "{{ name }}"),
        ("{{name }}", "{{ name }}"),
        ("{{name|lower}}", "{{ name|lower }}"),
        ("{{ name|lower}}", "{{ name|lower }}"),
        ("{{name|lower }}", "{{ name|lower }}"),
        ("{{name[0]}}", "{{ name[0] }}"),
        ("{{ name[0]}}", "{{ name[0] }}"),
        ("{{name[0] }}", "{{ name[0] }}"),
        ("{{name.replace('-', '_')}}", "{{ name.replace('-', '_') }}"),
        ("{{ name.replace('-', '_')}}", "{{ name.replace('-', '_') }}"),
        ("{{name.replace('-', '_') }}", "{{ name.replace('-', '_') }}"),
        ("{{x.update({4:5})}}", "{{ x.update({4:5}) }}"),
        ("{{x.update({4:5}) }}", "{{ x.update({4:5}) }}"),
        ("{{ x.update({4:5})}}", "{{ x.update({4:5}) }}"),
    ],
)
def test_jinja2_vars_cleanup_raw_yaml(raw_yaml, res):
    assert _cleanup_raw_yaml(raw_yaml).strip() == res


def test_jinja2_vars_cleanup_recipe():
    raw_yaml = """\
{% set name = "MetPy" %}
{% set version = "0.12.0" %}
{% set sha256 = "4125fbbc2620e3702961fe012cb52bdaba5f609ec5f5458818617676044b7921" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/{{name[0]}}/{{name}}/{{name}}-{{version}}.tar.gz
  sha256: {{sha256}}

build:
    noarch: python
    script: "{{ PYTHON }} -m pip install . --no-deps -vv"
    number: 0

requirements:
  host:
    - python >=3.6
    - setuptools
    - pip
    - setuptools_scm

  run:
    - python >=3.6
    - matplotlib-base >=2.1.0
    - numpy >=1.13
    - scipy >=1.0
    - pint >=0.8
    - xarray >=0.10.7
    - pooch >=0.1
    - traitlets >=4.3.0
    - pandas >=0.22.0
    - pyproj >=1.9.4
    - cartopy >=0.15.0

test:
  imports:
    - metpy.calc
    - metpy.interpolate
    - metpy.io
    - metpy.plots
    - metpy.units

about:
  home: https://github.com/Unidata/MetPy
  license: BSD 3-Clause
  license_family: BSD
  license_file: LICENSE
  summary: 'MetPy is a collection of tools in Python for reading, visualizing and performing calculations with weather data.'
  description: |
    The space MetPy aims for is GEMPAK (and maybe NCL)-like functionality,
    in a way that plugs easily into the existing scientific Python ecosystem
    (numpy, scipy, matplotlib). So, if you take the average GEMPAK script for
    a weather map, you need to: read data, calculate a derived field, and
    show on a map/skew-T. One of the benefits hoped to achieve over GEMPAK
    is to make it easier to use these routines for any meteorological Python
    application; this means making it easy to pull out the LCL calculation
    and just use that, or re-use the Skew-T with your own data code. MetPy
    also prides itself on being well-documented and well-tested, so that
    on-going maintenance is easily manageable.
  doc_url: https://unidata.github.io/MetPy
  dev_url: https://github.com/Unidata/MetPy

extra:
  recipe-maintainers:
    - dopplershift
"""  # noqa

    clean_yml = """\
{% set name = "MetPy" %}
{% set version = "0.12.0" %}
{% set sha256 = "4125fbbc2620e3702961fe012cb52bdaba5f609ec5f5458818617676044b7921" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
    noarch: python
    script: "{{ PYTHON }} -m pip install . --no-deps -vv"
    number: 0

requirements:
  host:
    - python >=3.6
    - setuptools
    - pip
    - setuptools_scm

  run:
    - python >=3.6
    - matplotlib-base >=2.1.0
    - numpy >=1.13
    - scipy >=1.0
    - pint >=0.8
    - xarray >=0.10.7
    - pooch >=0.1
    - traitlets >=4.3.0
    - pandas >=0.22.0
    - pyproj >=1.9.4
    - cartopy >=0.15.0

test:
  imports:
    - metpy.calc
    - metpy.interpolate
    - metpy.io
    - metpy.plots
    - metpy.units

about:
  home: https://github.com/Unidata/MetPy
  license: BSD 3-Clause
  license_family: BSD
  license_file: LICENSE
  summary: 'MetPy is a collection of tools in Python for reading, visualizing and performing calculations with weather data.'
  description: |
    The space MetPy aims for is GEMPAK (and maybe NCL)-like functionality,
    in a way that plugs easily into the existing scientific Python ecosystem
    (numpy, scipy, matplotlib). So, if you take the average GEMPAK script for
    a weather map, you need to: read data, calculate a derived field, and
    show on a map/skew-T. One of the benefits hoped to achieve over GEMPAK
    is to make it easier to use these routines for any meteorological Python
    application; this means making it easy to pull out the LCL calculation
    and just use that, or re-use the Skew-T with your own data code. MetPy
    also prides itself on being well-documented and well-tested, so that
    on-going maintenance is easily manageable.
  doc_url: https://unidata.github.io/MetPy
  dev_url: https://github.com/Unidata/MetPy

extra:
  recipe-maintainers:
    - dopplershift
"""  # noqa

    assert not _should_filter(raw_yaml)

    assert clean_yml == _cleanup_raw_yaml(raw_yaml)
