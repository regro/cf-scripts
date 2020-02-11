import pytest

from conda_forge_tick.recipe_parser._parser import (
    _parse_jinja2_variables,
    _munge_line,
    _unmunge_line,
    CONDA_SELECTOR
)


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
"""

    jinja2_vars = _parse_jinja2_variables(meta_yaml)

    assert jinja2_vars == {
        'var1': 'name',
        'var2': 0.1,
        'var3': 5,
        'var4__###conda-selector###__py3k and win or (hi!)': 'foo',
        'var4__###conda-selector###__py3k and win': 'foo',
        'var4__###conda-selector###__win': 'bar',
    }
