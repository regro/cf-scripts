import io
import pytest

from conda_forge_tick.recipe_parser._parser import (
    _parse_jinja2_variables,
    _munge_line,
    _unmunge_line,
    _demunge_jinja2_vars,
    _remunge_jinja2_vars,
    _replace_jinja2_vars,
    _build_jinja2_expr_tmp,
)

from conda_forge_tick.recipe_parser import CondaMetaYAML, CONDA_SELECTOR


@pytest.mark.parametrize('add_extra_req', [True, False])
def test_parsing(add_extra_req):
    meta_yaml = """\
{% set name = 'val1' %}  # [py2k]
{% set name = 'val2' %}#[py3k and win]
{% set version = '4.5.6' %}
{% set major_ver = version.split('.')[0] %}
{% set bad_ver = bad_version.split('.')[0] %}

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
    assert cm.jinja2_vars['name__###conda-selector###__py2k'] == 'val1'
    assert cm.jinja2_vars['name__###conda-selector###__py3k and win'] == 'val2'
    assert cm.jinja2_vars['version'] == '4.5.6'

    # check jinja2 expressions
    assert cm.jinja2_exprs["major_ver"] == "{% set major_ver = version.split('.')[0] %}"
    assert cm.jinja2_exprs["bad_ver"] == "{% set bad_ver = bad_version.split('.')[0] %}"

    # check it when we eval
    jinja2_exprs_evaled = cm.eval_jinja2_exprs(cm.jinja2_vars)
    assert jinja2_exprs_evaled["major_ver"] == 4

    # check selectors
    assert cm.meta['source']['sha256__###conda-selector###__py2k'] == 1
    assert cm.meta['source']['sha256__###conda-selector###__py3k and win'] == 5

    # check other keys
    assert cm.meta['build']['number'] == 10
    assert cm.meta['package']['name'] == '{{ name|lower }}'
    assert cm.meta['source']['url'] == 'foobar'
    if add_extra_req:
        assert cm.meta['requirements']['host'][0] == 'blah <{{ blarg }}'

    s = io.StringIO()
    cm.dump(s)
    s.seek(0)
    assert meta_yaml_canonical == s.read()

    # now add stuff and test outputs
    cm.jinja2_vars['foo'] = 'bar'
    cm.jinja2_vars['xfoo__###conda-selector###__win or osx'] = 10
    cm.jinja2_vars['build'] = 100
    cm.meta['about'] = 10
    cm.meta['extra__###conda-selector###__win'] = 'blah'
    cm.meta['extra__###conda-selector###__not win'] = 'not_win_blah'

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
        'blah\n',
        '{% set var2 = 5 %} # a comment\n',
        '{% set var3 = "none" %}#[sel2 and none and osx]\n',
        '{% set var4 = "val4" %}\n',
        '{% set var5 = "val5" %}\n',
    ]

    jinja2_vars = {
        'var1' + CONDA_SELECTOR + 'sel': 'val4',
        'var2': '4.5.6',
        'var3' + CONDA_SELECTOR + 'sel2 and none and osx': 'None',
        'var4': 'val4',
        'var5': 3.5,
        'new_var': 'new_val',
        'new_var' + CONDA_SELECTOR + 'py3k and win': 'new_val',
    }

    new_lines_true = [
        '{% set new_var = "new_val" %}\n',
        '{% set new_var = "new_val" %}  # [py3k and win]\n',
        '{% set var1 = "val4" %}  # [sel]\n',
        'blah\n',
        '{% set var2 = "4.5.6" %} # a comment\n',
        '{% set var3 = "None" %}  # [sel2 and none and osx]\n',
        '{% set var4 = "val4" %}\n',
        '{% set var5 = 3.5 %}\n',
    ]

    new_lines = _replace_jinja2_vars(lines, jinja2_vars)

    assert new_lines == new_lines_true


def test_munge_jinja2_vars():
    meta = {
        'val': '<{ var }}',
        'list': [
            'val',
            '<{ val_34 }}',
            {
                'fg': 2,
                'str': 'valish',
                'ab': '<{ val_again }}',
                'dict': {'hello': '<{ val_45 }}', 'int': 4},
                'list_again': [
                    'hi',
                    {'hello': '<{ val_12 }}', 'int': 5},
                    '<{ val_56 }}'
                ]
            }
        ]
    }

    demunged_meta_true = {
        'val': '{{ var }}',
        'list': [
            'val',
            '{{ val_34 }}',
            {
                'fg': 2,
                'str': 'valish',
                'ab': '{{ val_again }}',
                'dict': {'hello': '{{ val_45 }}', 'int': 4},
                'list_again': [
                    'hi',
                    {'hello': '{{ val_12 }}', 'int': 5},
                    '{{ val_56 }}'
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
    demunged_meta = _demunge_jinja2_vars(meta['list'], "<")
    assert demunged_meta_true['list'] == demunged_meta
    redemunged_meta = _remunge_jinja2_vars(demunged_meta, "<")
    assert redemunged_meta == meta['list']

    # string only?
    demunged_meta = _demunge_jinja2_vars('<{ val }}', "<")
    assert '{{ val }}' == demunged_meta
    redemunged_meta = _remunge_jinja2_vars(demunged_meta, "<")
    assert redemunged_meta == '<{ val }}'

    demunged_meta = _demunge_jinja2_vars('<<{ val }}', "<<")
    assert '{{ val }}' == demunged_meta
    redemunged_meta = _remunge_jinja2_vars(demunged_meta, "<<")
    assert redemunged_meta == '<<{ val }}'

    # an int
    demunged_meta = _demunge_jinja2_vars(5, "<")
    assert 5 == demunged_meta
    redemunged_meta = _remunge_jinja2_vars(demunged_meta, "<")
    assert redemunged_meta == 5


@pytest.mark.parametrize('line,correct_line,formatted_line', [
    ('  key1: val2\n', '  key1: val2\n', None),
    ('key2: val2\n', 'key2: val2\n', None),
    ('key3: val3#[sel3]\n',
     'key3' + CONDA_SELECTOR + 'sel3: val3\n',
     'key3: val3  # [sel3]\n'),
    ('key4: val4 #[sel4]\n',
     'key4' + CONDA_SELECTOR + 'sel4: val4 \n',
     'key4: val4  # [sel4]\n'),
    ('key5: val5  # [sel5]\n',
     'key5' + CONDA_SELECTOR + 'sel5: val5  \n',
     None),
    ('blah\n', 'blah\n', None),
    ('# [sel7]\n', '# [sel7]\n', None),
])
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
        'var1': 'name',
        'var2': 0.1,
        'var3': 5,
        'var4__###conda-selector###__py3k and win or (hi!)': 'foo',
        'var4__###conda-selector###__py3k and win': 'foo',
        'var4__###conda-selector###__win': 'bar',
    }
    assert jinja2_exprs == {
        "var5": "{% set var5 = var3 + 10 %}",
        "var7": "{% set var7 = var1.replace('n', 'm') %}",
    }

    tmpl = _build_jinja2_expr_tmp(jinja2_exprs)
    assert tmpl == """\
{% set var5 = var3 + 10 %}
{% set var7 = var1.replace('n', 'm') %}
var5: {{ var5 }}
var7: {{ var7 }}"""
