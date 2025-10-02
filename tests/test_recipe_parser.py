import io
import os
from pathlib import Path
from typing import Iterator

import pytest

from conda_forge_tick.recipe_parser import CONDA_SELECTOR, CondaMetaYAML
from conda_forge_tick.recipe_parser._parser import (
    _build_jinja2_expr_tmp,
    _demunge_jinja2_vars,
    _munge_line,
    _parse_jinja2_variables,
    _remunge_jinja2_vars,
    _replace_jinja2_vars,
    _unmunge_line,
)


def test_parsing_ml_jinja2():
    meta_yaml = """\
{% set namesel = 'val1' %}  # [py2k]
{% set name = 'val1' %}  # [py2k]
{% set name = 'val2' %}#[py3k and win]
{% set version = '4.5.6' %}
{% set major_ver = version.split('.')[0] %}
{% set bad_ver = bad_version.split('.')[0] %}
{% set vmajor,vminor,vpatch = version.split('.') %}
{% set crazy_string1 = ">=5,<7" ~ version %}
{% set crazy_string2 = '"' ~ version %}
{% set crazy_string3 = "'" ~ version %}
{% set crazy_string4 = "|" ~ version %}

{% set build = 0 %}
{% if False %}
{% set build = build + 100 %}
{% endif %}

{# this is a comment #}

package:
  name: {{ name|lower }}

source:
  url: foobar
  sha256: 1  # [py2k]
  sha256: 5#[py3k and win]

{% if (
    True
    and False
) %}
{% for i in [
    1, 2, 3, 4
] %}

{% for blah in [2, 3] %}
{% endfor %}
{% if False %}
{% endif %}
{% endfor %}

{% if False %}
{% endif %}
{% endif %}

{% set list = [
    blah1,
    blah2,
] %}

{% for i in [
    1, 2, 3, 4
] %}
{% for blah in [2, 3] %}
{% endfor %}
{% if False %}
{% endif %}
{% endfor %}

build:
  number: 10
"""

    meta_yaml_canonical = """\
{% set namesel = "val1" %}  # [py2k]
{% set name = "val1" %}  # [py2k]
{% set name = "val2" %}  # [py3k and win]
{% set version = "4.5.6" %}
{% set major_ver = version.split('.')[0] %}
{% set bad_ver = bad_version.split('.')[0] %}
{% set vmajor,vminor,vpatch = version.split('.') %}
{% set crazy_string1 = ">=5,<7" ~ version %}
{% set crazy_string2 = '"' ~ version %}
{% set crazy_string3 = "'" ~ version %}
{% set crazy_string4 = "|" ~ version %}

{% set build = 0 %}
{% if False %}
{% set build = build + 100 %}
{% endif %}

# this is a comment

package:
  name: {{ name|lower }}

source:
  url: foobar
  sha256: 1  # [py2k]
  sha256: 5  # [py3k and win]

{% if (
    True
    and False
) %}
{% for i in [
    1, 2, 3, 4
] %}

{% for blah in [2, 3] %}
{% endfor %}
{% if False %}
{% endif %}
{% endfor %}

{% if False %}
{% endif %}
{% endif %}

{% set list = [
    blah1,
    blah2,
] %}

{% for i in [
    1, 2, 3, 4
] %}
{% for blah in [2, 3] %}
{% endfor %}
{% if False %}
{% endif %}
{% endfor %}

build:
  number: 10
"""

    cm = CondaMetaYAML(meta_yaml)

    # check the jinja2 keys
    assert cm.jinja2_vars["namesel__###conda-selector###__py2k"] == "val1"
    assert cm.jinja2_vars["name__###conda-selector###__py2k"] == "val1"
    assert cm.jinja2_vars["name__###conda-selector###__py3k and win"] == "val2"
    assert cm.jinja2_vars["version"] == "4.5.6"

    # check jinja2 expressions
    assert cm.jinja2_exprs["major_ver"] == "{% set major_ver = version.split('.')[0] %}"
    assert cm.jinja2_exprs["bad_ver"] == "{% set bad_ver = bad_version.split('.')[0] %}"
    assert (
        cm.jinja2_exprs["vmajor"]
        == "{% set vmajor,vminor,vpatch = version.split('.') %}"
    )
    assert (
        cm.jinja2_exprs["vminor"]
        == "{% set vmajor,vminor,vpatch = version.split('.') %}"
    )
    assert (
        cm.jinja2_exprs["vpatch"]
        == "{% set vmajor,vminor,vpatch = version.split('.') %}"
    )
    assert (
        cm.jinja2_exprs["crazy_string1"]
        == '{% set crazy_string1 = ">=5,<7" ~ version %}'
    )
    assert (
        cm.jinja2_exprs["crazy_string2"] == "{% set crazy_string2 = '\"' ~ version %}"
    )
    assert (
        cm.jinja2_exprs["crazy_string3"] == '{% set crazy_string3 = "\'" ~ version %}'
    )
    assert cm.jinja2_exprs["crazy_string4"] == '{% set crazy_string4 = "|" ~ version %}'

    # check it when we eval
    jinja2_exprs_evaled = cm.eval_jinja2_exprs(cm.jinja2_vars)
    assert jinja2_exprs_evaled["major_ver"] == "4"
    assert jinja2_exprs_evaled["vmajor"] == "4"
    assert jinja2_exprs_evaled["vminor"] == "5"
    assert jinja2_exprs_evaled["vpatch"] == "6"
    assert jinja2_exprs_evaled["crazy_string1"] == ">=5,<74.5.6"
    assert jinja2_exprs_evaled["crazy_string2"] == '"4.5.6'
    assert jinja2_exprs_evaled["crazy_string3"] == "'4.5.6"
    assert jinja2_exprs_evaled["crazy_string4"] == "|4.5.6"

    # check selectors
    assert cm.meta["source"]["sha256__###conda-selector###__py2k"] == 1
    assert cm.meta["source"]["sha256__###conda-selector###__py3k and win"] == 5

    # check other keys
    assert cm.meta["build"]["number"] == 10
    assert cm.meta["package"]["name"] == "{{ name|lower }}"
    assert cm.meta["source"]["url"] == "foobar"

    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    assert meta_yaml_canonical == s.read()

    # now add stuff and test outputs
    cm.jinja2_vars["foo"] = "bar"
    cm.jinja2_vars["xfoo__###conda-selector###__win or osx"] = 10
    cm.jinja2_vars["build"] = 100
    cm.meta["about"] = 10
    cm.meta["extra__###conda-selector###__win"] = "blah"
    cm.meta["extra__###conda-selector###__not win"] = "not_win_blah"

    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    new_meta_yaml = s.read()

    true_new_meta_yaml = """\
{% set foo = "bar" %}
{% set xfoo = 10 %}  # [win or osx]
{% set namesel = "val1" %}  # [py2k]
{% set name = "val1" %}  # [py2k]
{% set name = "val2" %}  # [py3k and win]
{% set version = "4.5.6" %}
{% set major_ver = version.split('.')[0] %}
{% set bad_ver = bad_version.split('.')[0] %}
{% set vmajor,vminor,vpatch = version.split('.') %}
{% set crazy_string1 = ">=5,<7" ~ version %}
{% set crazy_string2 = '"' ~ version %}
{% set crazy_string3 = "'" ~ version %}
{% set crazy_string4 = "|" ~ version %}

{% set build = 100 %}
{% if False %}
{% set build = build + 100 %}
{% endif %}

# this is a comment

package:
  name: {{ name|lower }}

source:
  url: foobar
  sha256: 1  # [py2k]
  sha256: 5  # [py3k and win]

{% if (
    True
    and False
) %}
{% for i in [
    1, 2, 3, 4
] %}

{% for blah in [2, 3] %}
{% endfor %}
{% if False %}
{% endif %}
{% endfor %}

{% if False %}
{% endif %}
{% endif %}

{% set list = [
    blah1,
    blah2,
] %}

{% for i in [
    1, 2, 3, 4
] %}
{% for blah in [2, 3] %}
{% endfor %}
{% if False %}
{% endif %}
{% endfor %}

build:
  number: 10
"""

    true_new_meta_yaml += """\
about: 10
extra: blah  # [win]
extra: not_win_blah  # [not win]
"""

    assert new_meta_yaml == true_new_meta_yaml


@pytest.mark.parametrize("add_extra_req", [True, False])
def test_parsing(add_extra_req):
    meta_yaml = """\
{% set name = 'val1' %}  # [py2k]
{% set name = 'val2' %}#[py3k and win]
{% set version = '4.5.6' %}
{% set major_ver = version.split('.')[0] %}
{% set bad_ver = bad_version.split('.')[0] %}
{% set vmajor,vminor,vpatch = version.split('.') %}
{% set crazy_string1 = ">=5,<7" ~ version %}
{% set crazy_string2 = '"' ~ version %}
{% set crazy_string3 = "'" ~ version %}
{% set crazy_string4 = "|" ~ version %}

{% set build = 0 %}
{% if False %}
{% set build = build + 100 %}
{% endif %}

package:
  name: {{ name|lower }}

source:
  url: foobar
  sha256: 1  # [py2k]
  sha256: 5#[py3k and win]

build:
  number: 10
"""

    if add_extra_req:
        meta_yaml += """\
requirements:
  host:
    - blah <{{ blarg }}
"""

    meta_yaml_canonical = """\
{% set name = "val1" %}  # [py2k]
{% set name = "val2" %}  # [py3k and win]
{% set version = "4.5.6" %}
{% set major_ver = version.split('.')[0] %}
{% set bad_ver = bad_version.split('.')[0] %}
{% set vmajor,vminor,vpatch = version.split('.') %}
{% set crazy_string1 = ">=5,<7" ~ version %}
{% set crazy_string2 = '"' ~ version %}
{% set crazy_string3 = "'" ~ version %}
{% set crazy_string4 = "|" ~ version %}

{% set build = 0 %}
{% if False %}
{% set build = build + 100 %}
{% endif %}

package:
  name: {{ name|lower }}

source:
  url: foobar
  sha256: 1  # [py2k]
  sha256: 5  # [py3k and win]

build:
  number: 10
"""

    if add_extra_req:
        meta_yaml_canonical += """\
requirements:
  host:
    - blah <{{ blarg }}
"""

    cm = CondaMetaYAML(meta_yaml)

    # check the jinja2 keys
    assert cm.jinja2_vars["name__###conda-selector###__py2k"] == "val1"
    assert cm.jinja2_vars["name__###conda-selector###__py3k and win"] == "val2"
    assert cm.jinja2_vars["version"] == "4.5.6"

    # check jinja2 expressions
    assert cm.jinja2_exprs["major_ver"] == "{% set major_ver = version.split('.')[0] %}"
    assert cm.jinja2_exprs["bad_ver"] == "{% set bad_ver = bad_version.split('.')[0] %}"
    assert (
        cm.jinja2_exprs["vmajor"]
        == "{% set vmajor,vminor,vpatch = version.split('.') %}"
    )
    assert (
        cm.jinja2_exprs["vminor"]
        == "{% set vmajor,vminor,vpatch = version.split('.') %}"
    )
    assert (
        cm.jinja2_exprs["vpatch"]
        == "{% set vmajor,vminor,vpatch = version.split('.') %}"
    )
    assert (
        cm.jinja2_exprs["crazy_string1"]
        == '{% set crazy_string1 = ">=5,<7" ~ version %}'
    )
    assert (
        cm.jinja2_exprs["crazy_string2"] == "{% set crazy_string2 = '\"' ~ version %}"
    )
    assert (
        cm.jinja2_exprs["crazy_string3"] == '{% set crazy_string3 = "\'" ~ version %}'
    )
    assert cm.jinja2_exprs["crazy_string4"] == '{% set crazy_string4 = "|" ~ version %}'

    # check it when we eval
    jinja2_exprs_evaled = cm.eval_jinja2_exprs(cm.jinja2_vars)
    assert jinja2_exprs_evaled["major_ver"] == "4"
    assert jinja2_exprs_evaled["vmajor"] == "4"
    assert jinja2_exprs_evaled["vminor"] == "5"
    assert jinja2_exprs_evaled["vpatch"] == "6"
    assert jinja2_exprs_evaled["crazy_string1"] == ">=5,<74.5.6"
    assert jinja2_exprs_evaled["crazy_string2"] == '"4.5.6'
    assert jinja2_exprs_evaled["crazy_string3"] == "'4.5.6"
    assert jinja2_exprs_evaled["crazy_string4"] == "|4.5.6"

    # check selectors
    assert cm.meta["source"]["sha256__###conda-selector###__py2k"] == 1
    assert cm.meta["source"]["sha256__###conda-selector###__py3k and win"] == 5

    # check other keys
    assert cm.meta["build"]["number"] == 10
    assert cm.meta["package"]["name"] == "{{ name|lower }}"
    assert cm.meta["source"]["url"] == "foobar"
    if add_extra_req:
        assert cm.meta["requirements"]["host"][0] == "blah <{{ blarg }}"

    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    assert meta_yaml_canonical == s.read()

    # now add stuff and test outputs
    cm.jinja2_vars["foo"] = "bar"
    cm.jinja2_vars["xfoo__###conda-selector###__win or osx"] = 10
    cm.jinja2_vars["build"] = 100
    cm.meta["about"] = 10
    cm.meta["extra__###conda-selector###__win"] = "blah"
    cm.meta["extra__###conda-selector###__not win"] = "not_win_blah"

    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    new_meta_yaml = s.read()

    true_new_meta_yaml = """\
{% set foo = "bar" %}
{% set xfoo = 10 %}  # [win or osx]
{% set name = "val1" %}  # [py2k]
{% set name = "val2" %}  # [py3k and win]
{% set version = "4.5.6" %}
{% set major_ver = version.split('.')[0] %}
{% set bad_ver = bad_version.split('.')[0] %}
{% set vmajor,vminor,vpatch = version.split('.') %}
{% set crazy_string1 = ">=5,<7" ~ version %}
{% set crazy_string2 = '"' ~ version %}
{% set crazy_string3 = "'" ~ version %}
{% set crazy_string4 = "|" ~ version %}

{% set build = 100 %}
{% if False %}
{% set build = build + 100 %}
{% endif %}

package:
  name: {{ name|lower }}

source:
  url: foobar
  sha256: 1  # [py2k]
  sha256: 5  # [py3k and win]

build:
  number: 10
"""

    if add_extra_req:
        true_new_meta_yaml += """\
requirements:
  host:
    - blah <{{ blarg }}
"""

    true_new_meta_yaml += """\
about: 10
extra: blah  # [win]
extra: not_win_blah  # [not win]
"""

    assert new_meta_yaml == true_new_meta_yaml


def test_replace_jinja2_vars():
    lines = [
        '{% set var1 = "val1" %}  # [sel]\n',
        "blah\n",
        "{% set var2 = 5 %} # a comment\n",
        '{% set var3 = "none" %}#[sel2 and none and osx]\n',
        '{% set var4 = "val4" %}\n',
        '{% set var5 = "val5" %}\n',
    ]

    jinja2_vars = {
        "var1" + CONDA_SELECTOR + "sel": "val4",
        "var2": "4.5.6",
        "var3" + CONDA_SELECTOR + "sel2 and none and osx": "None",
        "var4": "val4",
        "var5": 3.5,
        "new_var": "new_val",
        "new_var" + CONDA_SELECTOR + "py3k and win": "new_val",
    }

    new_lines_true = [
        '{% set new_var = "new_val" %}\n',
        '{% set new_var = "new_val" %}  # [py3k and win]\n',
        '{% set var1 = "val4" %}  # [sel]\n',
        "blah\n",
        '{% set var2 = "4.5.6" %} # a comment\n',
        '{% set var3 = "None" %}  # [sel2 and none and osx]\n',
        '{% set var4 = "val4" %}\n',
        "{% set var5 = 3.5 %}\n",
    ]

    new_lines = _replace_jinja2_vars(lines, jinja2_vars)

    assert new_lines == new_lines_true


def test_munge_jinja2_vars():
    meta = {
        "val": "<{ var }}",
        "list": [
            "val",
            "<{ val_34 }}",
            {
                "fg": 2,
                "str": "valish",
                "ab": "<{ val_again }}",
                "dict": {"hello": "<{ val_45 }}", "int": 4},
                "list_again": [
                    "hi",
                    {"hello": "<{ val_12 }}", "int": 5},
                    "<{ val_56 }}",
                ],
            },
        ],
    }

    demunged_meta_true = {
        "val": "{{ var }}",
        "list": [
            "val",
            "{{ val_34 }}",
            {
                "fg": 2,
                "str": "valish",
                "ab": "{{ val_again }}",
                "dict": {"hello": "{{ val_45 }}", "int": 4},
                "list_again": [
                    "hi",
                    {"hello": "{{ val_12 }}", "int": 5},
                    "{{ val_56 }}",
                ],
            },
        ],
    }

    # dict
    demunged_meta = _demunge_jinja2_vars(meta, "<")
    assert demunged_meta_true == demunged_meta
    redemunged_meta = _remunge_jinja2_vars(demunged_meta, "<")
    assert redemunged_meta == meta

    # start with list
    demunged_meta = _demunge_jinja2_vars(meta["list"], "<")
    assert demunged_meta_true["list"] == demunged_meta
    redemunged_meta = _remunge_jinja2_vars(demunged_meta, "<")
    assert redemunged_meta == meta["list"]

    # string only?
    demunged_meta = _demunge_jinja2_vars("<{ val }}", "<")
    assert "{{ val }}" == demunged_meta
    redemunged_meta = _remunge_jinja2_vars(demunged_meta, "<")
    assert redemunged_meta == "<{ val }}"

    demunged_meta = _demunge_jinja2_vars("<<{ val }}", "<<")
    assert "{{ val }}" == demunged_meta
    redemunged_meta = _remunge_jinja2_vars(demunged_meta, "<<")
    assert redemunged_meta == "<<{ val }}"

    # an int
    demunged_meta = _demunge_jinja2_vars(5, "<")
    assert 5 == demunged_meta
    redemunged_meta = _remunge_jinja2_vars(demunged_meta, "<")
    assert redemunged_meta == 5


@pytest.mark.parametrize(
    "line,correct_line,formatted_line",
    [
        ("  key1: val2\n", "  key1: val2\n", None),
        ("key2: val2\n", "key2: val2\n", None),
        (
            "key3: val3#[sel3]\n",
            "key3" + CONDA_SELECTOR + "sel3: val3\n",
            "key3: val3  # [sel3]\n",
        ),
        (
            "key4: val4 #[sel4]\n",
            "key4" + CONDA_SELECTOR + "sel4: val4 \n",
            "key4: val4  # [sel4]\n",
        ),
        ("key5: val5  # [sel5]\n", "key5" + CONDA_SELECTOR + "sel5: val5  \n", None),
        ("blah\n", "blah\n", None),
        ("# [sel7]\n", "# [sel7]\n", None),
    ],
)
def test_munge_lines(line, correct_line, formatted_line):
    munged_line = _munge_line(line)
    assert munged_line == correct_line
    unmunged_line = _unmunge_line(munged_line)
    if formatted_line is None:
        assert unmunged_line == line
    else:
        assert unmunged_line == formatted_line
        assert unmunged_line != line


def test_parse_jinja2_variables():
    meta_yaml = """\
{% set var1 = "name" %}
{% set var2 = 0.1 %}
  {% set var3 = 5 %}

# comments

gh:
  hi:
    other: other text

  {% set var4 = 'foo' %}  # [py3k and win or (hi!)]

{% set var4 = 'foo' %} #[py3k and win]

{% set var4 = 'bar' %}#[win]

{% set var5 = var3 + 10 %}
{% set var7 = var1.replace('n', 'm') %}
"""

    jinja2_vars, jinja2_exprs = _parse_jinja2_variables(meta_yaml)

    assert jinja2_vars == {
        "var1": "name",
        "var2": 0.1,
        "var3": 5,
        "var4__###conda-selector###__py3k and win or (hi!)": "foo",
        "var4__###conda-selector###__py3k and win": "foo",
        "var4__###conda-selector###__win": "bar",
    }
    assert jinja2_exprs == {
        "var5": "{% set var5 = var3 + 10 %}",
        "var7": "{% set var7 = var1.replace('n', 'm') %}",
    }

    tmpl = _build_jinja2_expr_tmp(jinja2_exprs)
    assert (
        tmpl
        == """\
{% set var5 = var3 + 10 %}
{% set var7 = var1.replace('n', 'm') %}
var5: >-
  {{ var5 }}
var7: >-
  {{ var7 }}"""
    )


def test_recipe_parses_islpy():
    meta_yaml_ok = """\
{% set name = "islpy" %}
{% set version = "2020.2.2" %}
{% set sha256 = "7eb7dfa41d6a67d9ee4ea4bb9f08bdbcbee42b364502136b7882cfd80ff427e0" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  number: 0

requirements:
  build:
    - python                                 # [build_platform != target_platform]
    - cross-python_{{ target_platform }}     # [build_platform != target_platform]
    - pybind11                               # [build_platform != target_platform]
    - {{ compiler('cxx') }}
  host:
    - python
    - setuptools
    - six
    - pybind11
    - isl
  run:
    - python
    - six
    # Need the same version of isl we had when the package was built
    - {{ pin_compatible("isl", max_pin="x.x.x") }}

test:
  requires:
    - pytest
  imports:
    - islpy

  source_files:
    - test
  commands:
    - cd test && python -m pytest

about:
  home: http://github.com/inducer/islpy
  license: MIT
  license_file:
    - doc/misc.rst
  license_family: MIT
  summary: Wrapper around isl, an integer set library

  description: |
    islpy is a Python wrapper around Sven Verdoolaege's
    [isl](http://www.kotnet.org/~skimo/isl/), a library for manipulating
    sets and relations of integer points bounded by linear constraints.

    Supported operations on sets include

    -   intersection, union, set difference,
    -   emptiness check,
    -   convex hull,
    -   (integer) affine hull,
    -   integer projection,
    -   computing the lexicographic minimum using parametric integer
        programming,
    -   coalescing, and
    -   parametric vertex enumeration.

    It also includes an ILP solver based on generalized basis reduction,
    transitive closures on maps (which may encode infinite graphs),
    dependence analysis and bounds on piecewise step-polynomials.

extra:
  recipe-maintainers:
    - inducer
"""  # noqa

    meta_yaml_notok = """\
{% set name = "islpy" %}
{% set version = "2020.2.2" %}
{% set sha256 = "7eb7dfa41d6a67d9ee4ea4bb9f08bdbcbee42b364502136b7882cfd80ff427e0" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  number: 0

requirements:
  build:
    - python                                 # [build_platform != target_platform]
    - cross-python_{{ target_platform }}     # [build_platform != target_platform]
    - pybind11                               # [build_platform != target_platform]
    - {{ compiler('cxx') }}
  host:
    - python
    - setuptools
    - six
    - pybind11
    - isl
  run:
    - python
    - six
    # Need the same version of isl we had when the package was built
    - {{ pin_compatible("isl", max_pin="x.x.x") }}

test:
  requires:
    - pytest
  imports:
    - islpy

  source_files:
    - test
  commands:
    - cd test && python -m pytest

about:
  home: http://github.com/inducer/islpy
  license: MIT
  license_file:
    - doc/misc.rst
  license_family: MIT
  summary: Wrapper around isl, an integer set library

  description: |

    islpy is a Python wrapper around Sven Verdoolaege's
    [isl](http://www.kotnet.org/~skimo/isl/), a library for manipulating
    sets and relations of integer points bounded by linear constraints.

    Supported operations on sets include

    -   intersection, union, set difference,
    -   emptiness check,
    -   convex hull,
    -   (integer) affine hull,
    -   integer projection,
    -   computing the lexicographic minimum using parametric integer
        programming,
    -   coalescing, and
    -   parametric vertex enumeration.

    It also includes an ILP solver based on generalized basis reduction,
    transitive closures on maps (which may encode infinite graphs),
    dependence analysis and bounds on piecewise step-polynomials.

extra:
  recipe-maintainers:
    - inducer
"""  # noqa

    cm = CondaMetaYAML(meta_yaml_ok)
    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    assert meta_yaml_ok == s.read()

    cm = CondaMetaYAML(meta_yaml_notok)
    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    assert meta_yaml_notok != s.read()


def test_recipe_parses_fftw():
    recipe = """\
{% set version = "3.3.9" %}
{% set build = 1 %}


# ensure mpi is defined (needed for conda-smithy recipe-lint)
{% set mpi = mpi or 'nompi' %}

package:
  name: fftw
  version: {{ version }}

source:
  fn: fftw-{{ version }}.tar.gz
  url: http://www.fftw.org/fftw-{{ version }}.tar.gz
  sha256: bf2c7ce40b04ae811af714deb512510cc2c17b9ab9d6ddcf49fe4487eea7af3d

build:
  # prioritize nompi variant via build number
  {% if mpi == 'nompi' %}
  {% set build = build + 100 %}
  {% endif %}
  number: {{ build }}

  # add build string so packages can depend on
  # mpi or nompi variants explicitly:
  # `pkg * mpi_mpich_*` for mpich
  # `pkg * mpi_*` for any mpi
  # `pkg * nompi_*` for no mpi
  {% if mpi != 'nompi' %}
  {% set mpi_prefix = "mpi_" + mpi %}
  {% else %}
  {% set mpi_prefix = "nompi" %}
  {% endif %}
  string: "{{ mpi_prefix }}_h{{ PKG_HASH }}_{{ build }}"

  run_exports:
    - {{ pin_compatible('fftw', max_pin='x') }}
  {% if mpi != 'nompi' %}
    - fftw * {{ mpi_prefix }}_*
  {% endif %}

requirements:
  build:
    - perl 5.*  # [not win]
    - cmake  # [win]
    - {{ compiler('c') }}
    - {{ compiler('fortran') }}  # [not win]
    - llvm-openmp >=4.0.1  # [osx]
    - make      # [unix]
    - autoconf  # [unix]
    - automake  # [unix]
    - gettext   # [unix]
    - m4        # [unix]
    - libtool   # [unix]
    - {{ mpi }}  # [build_platform != target_platform and mpi == 'openmpi']
  host:
    - {{ mpi }}  # [mpi != 'nompi']
    - llvm-openmp >=4.0.1  # [osx]
  run:
    - llvm-openmp >=4.0.1  # [osx]

test:
  requires:
    - python
  commands:
    # Verify library contains Fortran symbols
    - strings ${PREFIX}/lib/libfftw3.a | grep -q dfftw || exit 1  # [not win]

    # Verify existence of library files
    - test -f ${PREFIX}/lib/libfftw3f.a || exit 1           # [not win]
    - test -f ${PREFIX}/lib/libfftw3.a || exit 1            # [not win]
    - test -f ${PREFIX}/lib/libfftw3l.a || exit 1           # [not win]
    - test -f ${PREFIX}/lib/libfftw3f_threads.a || exit 1   # [not win]
    - test -f ${PREFIX}/lib/libfftw3_threads.a || exit 1    # [not win]
    - test -f ${PREFIX}/lib/libfftw3l_threads.a || exit 1   # [not win]
    - test -f ${PREFIX}/lib/libfftw3f_omp.a || exit 1       # [not win]
    - test -f ${PREFIX}/lib/libfftw3_omp.a || exit 1        # [not win]
    - test -f ${PREFIX}/lib/libfftw3l_omp.a || exit 1       # [not win]

    # Verify headers are installed
    - test -f ${PREFIX}/include/fftw3.h || exit 1           # [not win]
    - if not exist %LIBRARY_INC%\\fftw3.h exit 1            # [win]

    # Verify shared libraries are installed
    {% set fftw_libs = [
            "libfftw3",
            "libfftw3_threads",
            "libfftw3f",
            "libfftw3f_threads",
            "libfftw3l",
            "libfftw3l_threads",
    ] %}
    {% set fftw_omp_libs = [
            "libfftw3_omp",
            "libfftw3f_omp",
            "libfftw3l_omp",
    ] %}
    {% set fftw_mpi_libs = [
            "libfftw3_mpi",
            "libfftw3f_mpi",
            "libfftw3l_mpi",
    ] %}

    {% for lib in fftw_libs %}
    - python -c "import ctypes; ctypes.cdll[r'${PREFIX}/lib/{{ lib }}${SHLIB_EXT}']"  # [unix]
    {% endfor %}

    {% for lib in fftw_omp_libs %}
    - python -c "import ctypes; ctypes.cdll[r'${PREFIX}/lib/{{ lib }}${SHLIB_EXT}']"  # [unix]
    {% endfor %}

    {% if mpi != 'nompi' %}
    {% for lib in fftw_mpi_libs %}
    # you need to link to the mpi libs to load the dll, so we just test
    # if it exists
    - test -f ${PREFIX}/lib/{{ lib }}${SHLIB_EXT} || exit 1  # [unix]
    {% endfor %}
    {% endif %}

    {% set fftw_libs = ["fftw3f", "fftw3"] %}

    {% for base in fftw_libs %}
    - if not exist %LIBRARY_LIB%\\{{ base }}.lib exit 1  # [win]
    - if not exist %LIBRARY_BIN%\\{{ base }}.dll exit 1  # [win]
    {% endfor %}

about:
  home: http://fftw.org
  license: GPL-2.0-or-later
  license_file: COPYING
  summary: "The fastest Fourier transform in the west."

extra:
  recipe-maintainers:
    - alexbw
    - jakirkham
    - grlee77
    - jschueller
    - egpbos
"""  # noqa

    recipe_parsed = """\
{% set version = "3.3.9" %}
{% set build = 1 %}


# ensure mpi is defined (needed for conda-smithy recipe-lint)
{% set mpi = mpi or 'nompi' %}

package:
  name: fftw
  version: {{ version }}

source:
  fn: fftw-{{ version }}.tar.gz
  url: http://www.fftw.org/fftw-{{ version }}.tar.gz
  sha256: bf2c7ce40b04ae811af714deb512510cc2c17b9ab9d6ddcf49fe4487eea7af3d

build:
  # prioritize nompi variant via build number
  {% if mpi == 'nompi' %}
  {% set build = build + 100 %}
  {% endif %}
  number: {{ build }}

  # add build string so packages can depend on
  # mpi or nompi variants explicitly:
  # `pkg * mpi_mpich_*` for mpich
  # `pkg * mpi_*` for any mpi
  # `pkg * nompi_*` for no mpi
  {% if mpi != 'nompi' %}
  {% set mpi_prefix = "mpi_" + mpi %}
  {% else %}
  {% set mpi_prefix = "nompi" %}
  {% endif %}
  string: "{{ mpi_prefix }}_h{{ PKG_HASH }}_{{ build }}"

  run_exports:
    - {{ pin_compatible('fftw', max_pin='x') }}
  {% if mpi != 'nompi' %}
    - fftw * {{ mpi_prefix }}_*
  {% endif %}

requirements:
  build:
    - perl 5.*  # [not win]
    - cmake  # [win]
    - {{ compiler('c') }}
    - {{ compiler('fortran') }}  # [not win]
    - llvm-openmp >=4.0.1  # [osx]
    - make      # [unix]
    - autoconf  # [unix]
    - automake  # [unix]
    - gettext   # [unix]
    - m4        # [unix]
    - libtool   # [unix]
    - {{ mpi }}  # [build_platform != target_platform and mpi == 'openmpi']
  host:
    - {{ mpi }}  # [mpi != 'nompi']
    - llvm-openmp >=4.0.1  # [osx]
  run:
    - llvm-openmp >=4.0.1  # [osx]

test:
  requires:
    - python
  commands:
    # Verify library contains Fortran symbols
    - strings ${PREFIX}/lib/libfftw3.a | grep -q dfftw || exit 1  # [not win]

    # Verify existence of library files
    - test -f ${PREFIX}/lib/libfftw3f.a || exit 1           # [not win]
    - test -f ${PREFIX}/lib/libfftw3.a || exit 1            # [not win]
    - test -f ${PREFIX}/lib/libfftw3l.a || exit 1           # [not win]
    - test -f ${PREFIX}/lib/libfftw3f_threads.a || exit 1   # [not win]
    - test -f ${PREFIX}/lib/libfftw3_threads.a || exit 1    # [not win]
    - test -f ${PREFIX}/lib/libfftw3l_threads.a || exit 1   # [not win]
    - test -f ${PREFIX}/lib/libfftw3f_omp.a || exit 1       # [not win]
    - test -f ${PREFIX}/lib/libfftw3_omp.a || exit 1        # [not win]
    - test -f ${PREFIX}/lib/libfftw3l_omp.a || exit 1       # [not win]

    # Verify headers are installed
    - test -f ${PREFIX}/include/fftw3.h || exit 1           # [not win]
    - if not exist %LIBRARY_INC%\\fftw3.h exit 1            # [win]

    # Verify shared libraries are installed
    {% set fftw_libs = [
            "libfftw3",
            "libfftw3_threads",
            "libfftw3f",
            "libfftw3f_threads",
            "libfftw3l",
            "libfftw3l_threads",
    ] %}
    {% set fftw_omp_libs = [
            "libfftw3_omp",
            "libfftw3f_omp",
            "libfftw3l_omp",
    ] %}
    {% set fftw_mpi_libs = [
            "libfftw3_mpi",
            "libfftw3f_mpi",
            "libfftw3l_mpi",
    ] %}

    {% for lib in fftw_libs %}
    - python -c "import ctypes; ctypes.cdll[r'${PREFIX}/lib/{{ lib }}${SHLIB_EXT}']"  # [unix]
    {% endfor %}

    {% for lib in fftw_omp_libs %}
    - python -c "import ctypes; ctypes.cdll[r'${PREFIX}/lib/{{ lib }}${SHLIB_EXT}']"  # [unix]
    {% endfor %}

    {% if mpi != 'nompi' %}
    {% for lib in fftw_mpi_libs %}
    # you need to link to the mpi libs to load the dll, so we just test
    # if it exists
    - test -f ${PREFIX}/lib/{{ lib }}${SHLIB_EXT} || exit 1  # [unix]
    {% endfor %}
    {% endif %}

    {% set fftw_libs = ["fftw3f", "fftw3"] %}

    {% for base in fftw_libs %}
    - if not exist %LIBRARY_LIB%\\{{ base }}.lib exit 1  # [win]
    - if not exist %LIBRARY_BIN%\\{{ base }}.dll exit 1  # [win]
    {% endfor %}

about:
  home: http://fftw.org
  license: GPL-2.0-or-later
  license_file: COPYING
  summary: "The fastest Fourier transform in the west."

extra:
  recipe-maintainers:
    - alexbw
    - jakirkham
    - grlee77
    - jschueller
    - egpbos
"""  # noqa

    cm = CondaMetaYAML(recipe)
    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    assert s.read() == recipe_parsed


def test_recipe_parses_fftw_raises():
    recipe = """\
{% set version = "3.3.9" %}
{% set build = 1 %}


# ensure mpi is defined (needed for conda-smithy recipe-lint)
{% set mpi = mpi or 'nompi' %}

package:
  name: fftw
  version: {{ version }}

source:
  fn: fftw-{{ version }}.tar.gz
  url: http://www.fftw.org/fftw-{{ version }}.tar.gz
  sha256: bf2c7ce40b04ae811af714deb512510cc2c17b9ab9d6ddcf49fe4487eea7af3d

build:
  # prioritize nompi variant via build number
  {% if mpi == 'nompi' %}
  {% set build = build + 100 %}
  {% endif %}
  number: {{ build }}

  # add build string so packages can depend on
  # mpi or nompi variants explicitly:
  # `pkg * mpi_mpich_*` for mpich
  # `pkg * mpi_*` for any mpi
  # `pkg * nompi_*` for no mpi
  {% if mpi != 'nompi' %}
  {% set mpi_prefix = "mpi_" + mpi %}
  {% else %}
  {% set mpi_prefix = "nompi" %}
  {% endif %}
  string: "{{ mpi_prefix }}_h{{ PKG_HASH }}_{{ build }}"

  run_exports:
    - {{ pin_compatible('fftw', max_pin='x') }}
  {% if mpi != 'nompi' %}
    - fftw * {{ mpi_prefix }}_*
  {% endif %}

requirements:
  build:
    - perl 5.*  # [not win]
    - cmake  # [win]
    - {{ compiler('c') }}
    - {{ compiler('fortran') }}  # [not win]
    - llvm-openmp >=4.0.1  # [osx]
    - make      # [unix]
    - autoconf  # [unix]
    - automake  # [unix]
    - gettext   # [unix]
    - m4        # [unix]
    - libtool   # [unix]
    - {{ mpi }}  # [build_platform != target_platform and mpi == 'openmpi']
  host:
    - {{ mpi }}  # [mpi != 'nompi']
    - llvm-openmp >=4.0.1  # [osx]
  run:
    - llvm-openmp >=4.0.1  # [osx]

test:
  requires:
    - python
  commands:
    # Verify library contains Fortran symbols
    - |                                                           # [not win]
      strings ${PREFIX}/lib/libfftw3.a | grep -q dfftw || exit 1  # [not win]

    # Verify existence of library files
    - test -f ${PREFIX}/lib/libfftw3f.a || exit 1           # [not win]
    - test -f ${PREFIX}/lib/libfftw3.a || exit 1            # [not win]
    - test -f ${PREFIX}/lib/libfftw3l.a || exit 1           # [not win]
    - test -f ${PREFIX}/lib/libfftw3f_threads.a || exit 1   # [not win]
    - test -f ${PREFIX}/lib/libfftw3_threads.a || exit 1    # [not win]
    - test -f ${PREFIX}/lib/libfftw3l_threads.a || exit 1   # [not win]
    - test -f ${PREFIX}/lib/libfftw3f_omp.a || exit 1       # [not win]
    - test -f ${PREFIX}/lib/libfftw3_omp.a || exit 1        # [not win]
    - test -f ${PREFIX}/lib/libfftw3l_omp.a || exit 1       # [not win]

    # Verify headers are installed
    - test -f ${PREFIX}/include/fftw3.h || exit 1           # [not win]
    - if not exist %LIBRARY_INC%\\fftw3.h exit 1            # [win]

    # Verify shared libraries are installed
    {% set fftw_libs = [
            "libfftw3",
            "libfftw3_threads",
            "libfftw3f",
            "libfftw3f_threads",
            "libfftw3l",
            "libfftw3l_threads",
    ] %}
    {% set fftw_omp_libs = [
            "libfftw3_omp",
            "libfftw3f_omp",
            "libfftw3l_omp",
    ] %}
    {% set fftw_mpi_libs = [
            "libfftw3_mpi",
            "libfftw3f_mpi",
            "libfftw3l_mpi",
    ] %}

    {% for lib in fftw_libs %}
    - python -c "import ctypes; ctypes.cdll[r'${PREFIX}/lib/{{ lib }}${SHLIB_EXT}']"  # [unix]
    {% endfor %}

    {% for lib in fftw_omp_libs %}
    - python -c "import ctypes; ctypes.cdll[r'${PREFIX}/lib/{{ lib }}${SHLIB_EXT}']"  # [unix]
    {% endfor %}

    {% if mpi != 'nompi' %}
    {% for lib in fftw_mpi_libs %}
    # you need to link to the mpi libs to load the dll, so we just test
    # if it exists
    - test -f ${PREFIX}/lib/{{ lib }}${SHLIB_EXT} || exit 1  # [unix]
    {% endfor %}
    {% endif %}

    {% set fftw_libs = ["fftw3f", "fftw3"] %}

    {% for base in fftw_libs %}
    - if not exist %LIBRARY_LIB%\\{{ base }}.lib exit 1  # [win]
    - if not exist %LIBRARY_BIN%\\{{ base }}.dll exit 1  # [win]
    {% endfor %}

about:
  home: http://fftw.org
  license: GPL-2.0-or-later
  license_file: COPYING
  summary: "The fastest Fourier transform in the west."

extra:
  recipe-maintainers:
    - alexbw
    - jakirkham
    - grlee77
    - jschueller
    - egpbos
"""  # noqa

    with pytest.raises(RuntimeError) as e:
        CondaMetaYAML(recipe)
    assert (
        "|                                                           # [not win]"
        in str(e.value)
    )


def test_recipe_parses_cupy():
    recipe = r"""{% set name = "cupy" -%}
{%- set version = "10.1.0" %}
{%- set sha256 = "ad28e7311b2023391f2278b7649828decdd9d9599848e18845eb4ab1b2d01936" -%}

{% if cuda_compiler_version in (None, "None", True, False) %}
{% set cuda_major = 0 %}
{% set cuda_minor = 0 %}
{% set cuda_major_minor = (0, 0) %}
{% else %}
{% set cuda_major = environ.get("cuda_compiler_version", "11.2").split(".")[0]|int %}
{% set cuda_minor = environ.get("cuda_compiler_version", "11.2").split(".")[1]|int %}
{% set cuda_major_minor = (cuda_major, cuda_minor) %}
{% endif %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  - url: https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz
    sha256: {{ sha256 }}

build:
  number: 0
  skip: true  # [(not win64 and not linux64 and (ppc64le and cuda_compiler_version != "10.2") and not (aarch64 and arm_variant_type == "sbsa")) or cuda_compiler_version in (undefined, "None")]
  script_env:
    # for some reason /usr/local/cuda is not added to $PATH in the docker image
    - CUDA_HOME  # [ppc64le or aarch64]
  script:
    # CuPy default detects CUDA from nvcc, but on Conda-Forge's dockers nvcc lives in a different place...
    # With conda-forge/nvcc-feedstock#58, CUDA_PATH is set correctly
    - export NVCC=$(which nvcc)                                                  # [linux]
    - echo "nvcc is $NVCC, CUDA path is $CUDA_PATH"                              # [linux]
    - for /f "tokens=* usebackq" %%f in (`where nvcc`) do (set "dummy=%%f" && call set "NVCC=%%dummy:\=\\%%")  # [win]
    - echo "nvcc is %NVCC%, CUDA path is %CUDA_PATH%"                                                          # [win]
    {% if cuda_major_minor >= (11, 2) %}
    - export CUSPARSELT_PATH=$PREFIX  # [linux64 or win]
    {% endif %}
    # Workaround __ieee128 error; see https://github.com/LLNL/blt/issues/341
    - export NVCC="$NVCC -Xcompiler -mno-float128"  # [ppc64le]

    - {{ PYTHON }} -m pip install . --no-deps -vv
    - if errorlevel 1 exit 1  # [win]

    # copy activate/deactivate scripts
    - mkdir -p "${PREFIX}/etc/conda/activate.d"                                               # [linux]
    - cp "${RECIPE_DIR}/activate.sh" "${PREFIX}/etc/conda/activate.d/cupy_activate.sh"        # [linux]
    - mkdir -p "${PREFIX}/etc/conda/deactivate.d"                                             # [linux]
    - cp "${RECIPE_DIR}/deactivate.sh" "${PREFIX}/etc/conda/deactivate.d/cupy_deactivate.sh"  # [linux]
    - if not exist %PREFIX%\etc\conda\activate.d mkdir %PREFIX%\etc\conda\activate.d          # [win]
    - copy %RECIPE_DIR%\activate.bat %PREFIX%\etc\conda\activate.d\cupy_activate.bat          # [win]
    - if not exist %PREFIX%\etc\conda\deactivate.d mkdir %PREFIX%\etc\conda\deactivate.d      # [win]
    - copy %RECIPE_DIR%\deactivate.bat %PREFIX%\etc\conda\deactivate.d\cupy_deactivate.bat    # [win]

    # enable CuPy's preload mechanism
    - mkdir -p "${SP_DIR}/cupy/.data/"                                                                                     # [linux]
    - if not exist %SP_DIR%\cupy\.data mkdir %SP_DIR%\cupy\.data                                                           # [win]
    {% if cuda_major_minor >= (11, 2) %}
    - cp ${RECIPE_DIR}/preload_config/linux64_cuda11_wheel.json ${SP_DIR}/cupy/.data/_wheel.json                           # [linux]
    - copy %RECIPE_DIR%\preload_config\win64_cuda11_wheel.json %SP_DIR%\cupy\.data\_wheel.json                             # [win]
    {% else %}
    - cp ${RECIPE_DIR}/preload_config/linux64_cuda{{ cuda_compiler_version }}_wheel.json ${SP_DIR}/cupy/.data/_wheel.json  # [linux]
    - copy %RECIPE_DIR%\preload_config\win64_cuda{{ cuda_compiler_version }}_wheel.json %SP_DIR%\cupy\.data\_wheel.json    # [win]
    {% endif %}
  missing_dso_whitelist:
    - '*/libcuda.*'  # [linux]
    - '*/nvcuda.dll'  # [win]
  ignore_run_exports_from:
    - cudnn  # [linux64 or ppc64le or win]
    - nccl  # [linux64 or ppc64le]
    - cutensor
    {% if cuda_major_minor >= (11, 2) %}
    - cusparselt  # [linux64 or win]
    {% endif %}

requirements:
  build:
    - {{ compiler("c") }}
    - {{ compiler("cxx") }}
    - {{ compiler("cuda") }}
    - sysroot_linux-64 2.17  # [linux]

  host:
    - python
    - pip
    - setuptools
    - cython >=0.29.22,<3
    - fastrlock >=0.5
    - cudnn  # [linux64 or ppc64le or win]
    - nccl >=2.8  # [linux64 or ppc64le]
    - cutensor
    {% if cuda_major_minor >= (11, 2) %}
    - cusparselt !=0.2.0.*  # [linux64 or win]
    {% endif %}

  run:
    - python
    - setuptools
    - fastrlock >=0.5
    - numpy >=1.18

  run_constrained:
    # Only GLIBC_2.17 or older symbols present
    - __glibc >=2.17      # [linux]
    - scipy >=1.4
    - optuna >=2
    - {{ pin_compatible('cudnn') }}  # [linux64 or ppc64le or win]
    - {{ pin_compatible('nccl') }}  # [linux64 or ppc64le]
    - {{ pin_compatible('cutensor', lower_bound='1.3') }}
    {% if cuda_major_minor >= (11, 2) %}
    - {{ pin_compatible('cusparselt', max_pin='x.x') }}  # [linux64 or win]
    {% endif %}

test:
  requires:
    - pytest
    - {{ compiler("c") }}
    - {{ compiler("cxx") }}
    - {{ compiler("cuda") }}  # tests need nvcc

  source_files:
    - tests

about:
  home: https://cupy.dev/
  license: MIT
  license_family: MIT
  license_file: LICENSE
  summary: |
    CuPy: NumPy & SciPy for GPU
  dev_url: https://github.com/cupy/cupy/
  doc_url: https://docs.cupy.dev/en/stable/

extra:
  recipe-maintainers:
    - jakirkham
    - leofang
    - kmaehashi
    - asi1024
    - emcastillo
    - toslunar
"""  # noqa

    recipe_parsed = r"""{% set name = "cupy" %}
{% set version = "10.1.0" %}
{% set sha256 = "ad28e7311b2023391f2278b7649828decdd9d9599848e18845eb4ab1b2d01936" %}

{% if cuda_compiler_version in (None, "None", True, False) %}
{% set cuda_major = 0 %}
{% set cuda_minor = 0 %}
{% set cuda_major_minor = (0, 0) %}
{% else %}
{% set cuda_major = environ.get("cuda_compiler_version", "11.2").split(".")[0]|int %}
{% set cuda_minor = environ.get("cuda_compiler_version", "11.2").split(".")[1]|int %}
{% set cuda_major_minor = (cuda_major, cuda_minor) %}
{% endif %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  - url: https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz
    sha256: {{ sha256 }}

build:
  number: 0
  skip: true  # [(not win64 and not linux64 and (ppc64le and cuda_compiler_version != "10.2") and not (aarch64 and arm_variant_type == "sbsa")) or cuda_compiler_version in (undefined, "None")]
  script_env:
    # for some reason /usr/local/cuda is not added to $PATH in the docker image
    - CUDA_HOME  # [ppc64le or aarch64]
  script:
    # CuPy default detects CUDA from nvcc, but on Conda-Forge's dockers nvcc lives in a different place...
    # With conda-forge/nvcc-feedstock#58, CUDA_PATH is set correctly
    - export NVCC=$(which nvcc)                                                  # [linux]
    - echo "nvcc is $NVCC, CUDA path is $CUDA_PATH"                              # [linux]
    - for /f "tokens=* usebackq" %%f in (`where nvcc`) do (set "dummy=%%f" && call set "NVCC=%%dummy:\=\\%%")  # [win]
    - echo "nvcc is %NVCC%, CUDA path is %CUDA_PATH%"                                                          # [win]
    {% if cuda_major_minor >= (11, 2) %}
    - export CUSPARSELT_PATH=$PREFIX  # [linux64 or win]
    {% endif %}
    # Workaround __ieee128 error; see https://github.com/LLNL/blt/issues/341
    - export NVCC="$NVCC -Xcompiler -mno-float128"  # [ppc64le]

    - {{ PYTHON }} -m pip install . --no-deps -vv
    - if errorlevel 1 exit 1  # [win]

    # copy activate/deactivate scripts
    - mkdir -p "${PREFIX}/etc/conda/activate.d"                                               # [linux]
    - cp "${RECIPE_DIR}/activate.sh" "${PREFIX}/etc/conda/activate.d/cupy_activate.sh"        # [linux]
    - mkdir -p "${PREFIX}/etc/conda/deactivate.d"                                             # [linux]
    - cp "${RECIPE_DIR}/deactivate.sh" "${PREFIX}/etc/conda/deactivate.d/cupy_deactivate.sh"  # [linux]
    - if not exist %PREFIX%\etc\conda\activate.d mkdir %PREFIX%\etc\conda\activate.d          # [win]
    - copy %RECIPE_DIR%\activate.bat %PREFIX%\etc\conda\activate.d\cupy_activate.bat          # [win]
    - if not exist %PREFIX%\etc\conda\deactivate.d mkdir %PREFIX%\etc\conda\deactivate.d      # [win]
    - copy %RECIPE_DIR%\deactivate.bat %PREFIX%\etc\conda\deactivate.d\cupy_deactivate.bat    # [win]

    # enable CuPy's preload mechanism
    - mkdir -p "${SP_DIR}/cupy/.data/"                                                                                     # [linux]
    - if not exist %SP_DIR%\cupy\.data mkdir %SP_DIR%\cupy\.data                                                           # [win]
    {% if cuda_major_minor >= (11, 2) %}
    - cp ${RECIPE_DIR}/preload_config/linux64_cuda11_wheel.json ${SP_DIR}/cupy/.data/_wheel.json                           # [linux]
    - copy %RECIPE_DIR%\preload_config\win64_cuda11_wheel.json %SP_DIR%\cupy\.data\_wheel.json                             # [win]
    {% else %}
    - cp ${RECIPE_DIR}/preload_config/linux64_cuda{{ cuda_compiler_version }}_wheel.json ${SP_DIR}/cupy/.data/_wheel.json  # [linux]
    - copy %RECIPE_DIR%\preload_config\win64_cuda{{ cuda_compiler_version }}_wheel.json %SP_DIR%\cupy\.data\_wheel.json    # [win]
    {% endif %}
  missing_dso_whitelist:
    - '*/libcuda.*'  # [linux]
    - '*/nvcuda.dll'  # [win]
  ignore_run_exports_from:
    - cudnn  # [linux64 or ppc64le or win]
    - nccl  # [linux64 or ppc64le]
    - cutensor
    {% if cuda_major_minor >= (11, 2) %}
    - cusparselt  # [linux64 or win]
    {% endif %}

requirements:
  build:
    - {{ compiler("c") }}
    - {{ compiler("cxx") }}
    - {{ compiler("cuda") }}
    - sysroot_linux-64 2.17  # [linux]

  host:
    - python
    - pip
    - setuptools
    - cython >=0.29.22,<3
    - fastrlock >=0.5
    - cudnn  # [linux64 or ppc64le or win]
    - nccl >=2.8  # [linux64 or ppc64le]
    - cutensor
    {% if cuda_major_minor >= (11, 2) %}
    - cusparselt !=0.2.0.*  # [linux64 or win]
    {% endif %}

  run:
    - python
    - setuptools
    - fastrlock >=0.5
    - numpy >=1.18

  run_constrained:
    # Only GLIBC_2.17 or older symbols present
    - __glibc >=2.17      # [linux]
    - scipy >=1.4
    - optuna >=2
    - {{ pin_compatible('cudnn') }}  # [linux64 or ppc64le or win]
    - {{ pin_compatible('nccl') }}  # [linux64 or ppc64le]
    - {{ pin_compatible('cutensor', lower_bound='1.3') }}
    {% if cuda_major_minor >= (11, 2) %}
    - {{ pin_compatible('cusparselt', max_pin='x.x') }}  # [linux64 or win]
    {% endif %}

test:
  requires:
    - pytest
    - {{ compiler("c") }}
    - {{ compiler("cxx") }}
    - {{ compiler("cuda") }}  # tests need nvcc

  source_files:
    - tests

about:
  home: https://cupy.dev/
  license: MIT
  license_family: MIT
  license_file: LICENSE
  summary: |
    CuPy: NumPy & SciPy for GPU
  dev_url: https://github.com/cupy/cupy/
  doc_url: https://docs.cupy.dev/en/stable/

extra:
  recipe-maintainers:
    - jakirkham
    - leofang
    - kmaehashi
    - asi1024
    - emcastillo
    - toslunar
"""  # noqa

    cm = CondaMetaYAML(recipe)
    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    assert s.read() == recipe_parsed


def test_recipe_parses_libcudss():
    recipe = r"""{% set version = "0.7.0.20" %}
{% set soversion = ".".join(version.split(".")[:3]) %}
{% set somajor = version.split(".")[0] %}

package:
  name: libcudss-split
  version: {{ version }}

{% set arm_variant_type = arm_variant_type | default("sbsa") %}
{% set cuda_compiler_version = cuda_compiler_version | default("None") %}

source:
  - url: "https://developer.download.nvidia.com/compute/cudss/redist/libcudss/linux-x86_64/libcudss-linux-x86_64-{{ version }}_cuda12-archive.tar.xz"  # [linux and x86_64 and (cuda_compiler_version or "").startswith("12")]
    sha256: "c98d5ef87e8b6a356b21a678715033b19620ce58b5fa64c97e25e6d3e76e42dc"  # [linux and x86_64 and (cuda_compiler_version or "").startswith("12")]
  - url: "https://developer.download.nvidia.com/compute/cudss/redist/libcudss/linux-x86_64/libcudss-linux-x86_64-{{ version }}_cuda13-archive.tar.xz"  # [linux and x86_64 and (cuda_compiler_version or "").startswith("13")]
    sha256: "939606e8d062ee0fc28094e7be19e22191662e8593bc7f5eec16220ad836feb9"  # [linux and x86_64 and (cuda_compiler_version or "").startswith("13")]
  - url: "https://developer.download.nvidia.com/compute/cudss/redist/libcudss/linux-sbsa/libcudss-linux-sbsa-{{ version }}_cuda12-archive.tar.xz"  # [linux and aarch64 and (cuda_compiler_version or "").startswith("12") and arm_variant_type == "sbsa"]
    sha256: "92f3425e7badcd2d6324efbe8c7ca314a36295ab550238f7772137c3652d7884"  # [linux and aarch64 and (cuda_compiler_version or "").startswith("12") and arm_variant_type == "sbsa"]
  - url: "https://developer.download.nvidia.com/compute/cudss/redist/libcudss/linux-sbsa/libcudss-linux-sbsa-{{ version }}_cuda13-archive.tar.xz"  # [linux and aarch64 and (cuda_compiler_version or "").startswith("13") and arm_variant_type == "sbsa"]
    sha256: "f915eb581ab965d0baa74cd1e529086fce00e9d14d9366da4480b5ef7fabb8a6"  # [linux and aarch64 and (cuda_compiler_version or "").startswith("13") and arm_variant_type == "sbsa"]
  - url: "https://developer.download.nvidia.com/compute/cudss/redist/libcudss/windows-x86_64/libcudss-windows-x86_64-{{ version }}_cuda12-archive.zip"  # [win and x86_64 and (cuda_compiler_version or "").startswith("12")]
    sha256: "69b7e5dc98f2d6242eb8e072d7a73e1f573d8a1bb65d97463ba72e9334d67f58"  # [win and x86_64 and (cuda_compiler_version or "").startswith("12")]
  - url: "https://developer.download.nvidia.com/compute/cudss/redist/libcudss/windows-x86_64/libcudss-windows-x86_64-{{ version }}_cuda13-archive.zip"  # [win and x86_64 and (cuda_compiler_version or "").startswith("13")]
    sha256: "a35f34a1995b5951cfe5b625e17d33ebe0e7e487476b5315a229cf348dcc2c0b"  # [win and x86_64 and (cuda_compiler_version or "").startswith("13")]
  - url: "https://developer.download.nvidia.com/compute/cudss/redist/libcudss/linux-aarch64/libcudss-linux-aarch64-{{ version }}_cuda12-archive.tar.xz"  # [linux and aarch64 and (cuda_compiler_version or "").startswith("12") and arm_variant_type == "tegra"]
    sha256: "ce3de5e6a0cee00fd1fc355881308ef0c692c6e14b6a5625aa35a7f9df98b846"  # [linux and aarch64 and (cuda_compiler_version or "").startswith("12") and arm_variant_type == "tegra"]
  - url: "https://developer.download.nvidia.com/compute/cudss/redist/libcudss/linux-aarch64/libcudss-linux-aarch64-{{ version }}_cuda13-archive.tar.xz"  # [linux and aarch64 and (cuda_compiler_version or "").startswith("13") and arm_variant_type == "tegra"]
    sha256: "c33768ac50caa36103facfec21a32b2c65ed1f1f085eaf153091dcaf734fdfc6"  # [linux and aarch64 and (cuda_compiler_version or "").startswith("13") and arm_variant_type == "tegra"]

build:
  number: 0
  skip: true  # [(cuda_compiler_version in (None, "None", "11.8")) or (not (linux64 or aarch64 or win64))]
  script:   # [win]
    - xcopy include %LIBRARY_INC% /E /I /Y /V  # [win]
    - xcopy lib %LIBRARY_LIB% /E /I /Y /V  # [win]
    - xcopy bin %LIBRARY_BIN% /E /I /Y /V  # [win]

requirements:
  build:
    - {{ compiler('c') }}
    - {{ compiler('cuda') }}
    - {{ compiler('cxx') }}
    - {{ stdlib("c") }}
    - cf-nvidia-tools 1  # [linux]

outputs:

  - name: libcudss
    build:
      ignore_run_exports_from:
        - libcublas-dev
      ignore_run_exports:
        - cuda-version
    files:
      - lib/libcudss.so.*                      # [linux]
      - lib/libcudss_mtlayer_*.so.*            # [linux]
      - Library/bin/cudss64_{{ somajor }}.dll  # [win]
      - Library/bin/cudss_mtlayer_*.dll        # [win]
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cuda') }}
        - {{ compiler('cxx') }}
        - {{ stdlib("c") }}
        - libgomp
      host:
        - cuda-version {{ cuda_compiler_version }}  # [cuda_compiler_version != "None"]
        - libcublas-dev
        - {{ pin_subpackage("libcudss-commlayer-nccl", exact=True) }}  # [linux]
        - {{ pin_subpackage("libcudss-commlayer-mpi", exact=True) }}  # [linux]
      run:
        - {{ pin_compatible('cuda-version', max_pin='x', min_pin='x') }}  # [cuda_compiler_version != "None"]
        - libcublas
      run_constrained:
        - libcudss0 <0.0.0a0
        - {{ pin_subpackage("libcudss-commlayer-nccl", exact=True) }}
        - {{ pin_subpackage("libcudss-commlayer-mpi", exact=True) }}
    test:
      requires:
        - libcudss-commlayer-nccl  # [linux]
        - libcudss-commlayer-mpi  # [linux]
      commands:
        - test -f $PREFIX/lib/libcudss.so.{{ soversion }}                # [linux]
        - test -L $PREFIX/lib/libcudss.so.{{ somajor }}                  # [linux]
        - test -f $PREFIX/lib/libcudss_mtlayer_gomp.so.{{ soversion }}   # [linux]
        - test -L $PREFIX/lib/libcudss_mtlayer_gomp.so.{{ somajor }}     # [linux]
        - test ! -f $PREFIX/lib/libcudss_static.a                        # [linux]
        - if not exist %LIBRARY_BIN%\\cudss64_{{ somajor }}.dll exit 1   # [win]
        - if not exist %LIBRARY_BIN%\\cudss_mtlayer_vcomp140.dll exit 1  # [win]
    about:
      summary: The NVIDIA cuDSS runtime library (with a pre-built threading layer for OpenMP).
      license: LicenseRef-NVIDIA-End-User-License-Agreement
      license_file: LICENSE
      description: >-
        This is a runtime package only. Developers should install libcudss-dev to build with cuDSS.

  - name: libcudss-dev
    build:
      run_exports:
        # Breaking changes every version until 1.0
        - {{ pin_subpackage("libcudss", max_pin="x.x.x") }}
    files:
      - lib/libcudss.so  # [linux]
      - include/cudss*  # [linux]
      - lib/cmake/cudss/cudss-config*  # [linux]
      - lib/cmake/cudss/cudss-targets*  # [linux]
      - Library/lib/cudss.lib  # [win]
      - Library/include/cudss*  # [win]
      - Library/lib/cmake/cudss/*  # [win]
    requirements:
      host:
        - {{ pin_subpackage("libcudss", exact=True) }}
      run:
        - {{ pin_subpackage("libcudss", exact=True) }}
      run_constrained:
    test:
      files:
        - test
      requires:   # [build_platform == target_platform]
        - {{ compiler("c") }}  # [build_platform == target_platform]
        - {{ compiler("cxx") }}  # [build_platform == target_platform]
        - {{ compiler('cuda') }}  # [build_platform == target_platform]
        - {{ stdlib("c") }}  # [build_platform == target_platform]
        - cmake  # [build_platform == target_platform]
        - ninja  # [build_platform == target_platform]
      commands:
        - test -f $PREFIX/include/cudss.h  # [linux]
        - test -f $PREFIX/include/cudss_distributed_interface.h  # [linux]
        - test -f $PREFIX/include/cudss_threading_interface.h  # [linux]
        - test -L $PREFIX/lib/libcudss.so  # [linux]
        - test ! -f $PREFIX/lib/libcudss_static.a  # [linux]
        - test ! -f $PREFIX/lib/cmake/cudss/cudss-static.targets.cmake  # [linux]
        - if not exist %LIBRARY_LIB%\\cudss.lib exit 1  # [win]
        - if not exist %LIBRARY_INC%\\cudss.h exit 1  # [win]
        - if not exist %LIBRARY_INC%\\cudss_distributed_interface.h exit 1  # [win]
        - if not exist %LIBRARY_INC%\\cudss_threading_interface.h exit 1  # [win]
        - if not exist %LIBRARY_LIB%\\cmake\\cudss\\cudss-config.cmake exit 1  # [win]
        - cmake ${CMAKE_ARGS} -GNinja test  # [build_platform == target_platform]
        - cmake --build .  # [build_platform == target_platform]
    # Metadata will be inherited from top-level

# loadable modules; optional and only needed at runtime

  - name: libcudss-commlayer-nccl
    build:
      skip: true  # [not linux]
    files:
      - lib/libcudss_commlayer_nccl.so.*  # [linux]
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - {{ compiler('cuda') }}
        - {{ stdlib("c") }}
      host:
        - cuda-version {{ cuda_compiler_version }}  # [cuda_compiler_version != "None"]
        - nccl
    test:
      commands:
        - test -f $PREFIX/lib/libcudss_commlayer_nccl.so.{{ soversion }}  # [linux]
        - test -L $PREFIX/lib/libcudss_commlayer_nccl.so.{{ somajor }}  # [linux]
    about:
      summary: Install this package to enable NCCL for cuDSS
      license: LicenseRef-NVIDIA-End-User-License-Agreement
      license_file: LICENSE
      description: >-
        This is a runtime package only. Developers should install libcudss-dev to build with cuDSS.

  - name: libcudss-commlayer-mpi
    build:
      skip: true  # [not linux]
    files:
      - lib/libcudss_commlayer_openmpi.so.*  # [linux]
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - {{ compiler('cuda') }}
        - {{ stdlib("c") }}
      host:
        - cuda-version {{ cuda_compiler_version }}  # [cuda_compiler_version != "None"]
        # collect channel pinning
        - openmpi
        # constrain to version that we actually built with
        - openmpi >=4.1.0,<6
    test:
      commands:
        - test -f $PREFIX/lib/libcudss_commlayer_openmpi.so.{{ soversion }}  # [linux]
        - test -L $PREFIX/lib/libcudss_commlayer_openmpi.so.{{ somajor }}  # [linux]
    about:
      summary: Install this package to enable MPI for cuDSS
      license: LicenseRef-NVIDIA-End-User-License-Agreement
      license_file: LICENSE
      description: >-
        This is a runtime package only. Developers should install libcudss-dev to build with cuDSS.

# NOTE: Metadata inheritance from this section to the outputs is all or nothing. Only the
# -dev package and the feedstock readme are inheriting this metadata.
about:
  home: https://developer.nvidia.com/cudss
  license: LicenseRef-NVIDIA-End-User-License-Agreement
  license_file: LICENSE
  license_url: https://docs.nvidia.com/cuda/cudss/license.html
  summary: The NVIDIA cuDSS development package.
  description: >-
    NVIDIA cuDSS is an optimized, first-generation GPU-accelerated Direct Sparse Solver library for solving linear systems with sparse matrices. Direct Sparse Solvers are an important part of numerical computing as they provide a general robust way of solving large linear systems without and are capable of taking advantage
    of both high compute throughput and memory bandwidth of the GPUs.
  doc_url: https://docs.nvidia.com/cuda/cudss/

extra:
  compute-subdir: cudss
  redist-json-name: libcudss
  recipe-maintainers:
    - conda-forge/cuda
    - kvoronin
  feedstock-name: libcudss
"""  # noqa

    cm = CondaMetaYAML(recipe)
    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    assert s.read() == recipe_parsed


def test_recipe_parses_strings_colons_quotes():
    recipe = """\
test:
  commands:
    - "DISPLAY=localhost:1.0 xvfb-run -a affinder --help"  # [linux]
    - 'DISPLAY=localhost:1.0 xvfb-run -a affinder --help'  # [linux]
    - "foo": bar  # [linux]
      blah: blah blah  # [linux]
      'ghg': ggsdf  # [linux]
"""

    recipe_correct = """\
test:
  commands:
    - "DISPLAY=localhost:1.0 xvfb-run -a affinder --help"  # [linux]
    - 'DISPLAY=localhost:1.0 xvfb-run -a affinder --help'  # [linux]
    - "foo": bar  # [linux]
      blah: blah blah  # [linux]
      'ghg': ggsdf  # [linux]
"""
    cm = CondaMetaYAML(recipe)
    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    new_recipe = s.read()
    assert new_recipe == recipe_correct


YAML_PATH = Path(__file__).parent / "test_yaml"


def collect_all_recipes(directory: Path) -> Iterator[Path]:
    # note: Path.walk() is available since Python 3.12
    for dirpath, _, filenames in os.walk(directory):
        for filename in filenames:
            if (
                filename.endswith("_correct.yaml")
                and "duplicate_lines_cleanup" not in filename
            ) or filename.endswith("_after_meta.yaml"):
                yield Path(dirpath) / filename


@pytest.mark.parametrize(
    "recipe_path",
    collect_all_recipes(YAML_PATH),
    ids=lambda x: str(x.relative_to(YAML_PATH)),
)
def test_recipe_parser_yaml_suite(recipe_path: Path):
    recipe = recipe_path.read_text()
    cm = CondaMetaYAML(recipe)
    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    assert s.read() == recipe
