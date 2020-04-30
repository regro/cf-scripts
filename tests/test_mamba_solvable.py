import os

import pytest

from conda_forge_tick.mamba_solver import is_recipe_solvable, _norm_spec


FEEDSTOCK_DIR = os.path.join(os.path.dirname(__file__), 'test_feedstock')


def test_is_recipe_solvable_ok():
    recipe_file = os.path.join(FEEDSTOCK_DIR, "recipe", "meta.yaml")
    os.makedirs(os.path.dirname(recipe_file), exist_ok=True)
    try:
        with open(recipe_file, "w") as fp:
            fp.write("""\
{% set name = "cf-autotick-bot-test-package" %}
{% set version = "0.9" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  path: .

build:
  number: 8

requirements:
  host:
    - python
    - pip
  run:
    - python

test:
  commands:
    - echo "works!"

about:
  home: https://github.com/regro/cf-scripts
  license: BSD-3-Clause
  license_family: BSD
  license_file: LICENSE
  summary: testing feedstock for the regro-cf-autotick-bot

extra:
  recipe-maintainers:
    - beckermr
    - conda-forge/bot
""")
        assert is_recipe_solvable(FEEDSTOCK_DIR)
    finally:
        try:
            os.remove(recipe_file)
        except Exception:
            pass


def test_is_recipe_solvable_notok():
    recipe_file = os.path.join(FEEDSTOCK_DIR, "recipe", "meta.yaml")
    os.makedirs(os.path.dirname(recipe_file), exist_ok=True)
    try:
        with open(recipe_file, "w") as fp:
            fp.write("""\
{% set name = "cf-autotick-bot-test-package" %}
{% set version = "0.9" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  path: .

build:
  number: 8

requirements:
  host:
    - python >=4.0  # [osx]
    - python  # [not osx]
    - pip
  run:
    - python

test:
  commands:
    - echo "works!"

about:
  home: https://github.com/regro/cf-scripts
  license: BSD-3-Clause
  license_family: BSD
  license_file: LICENSE
  summary: testing feedstock for the regro-cf-autotick-bot

extra:
  recipe-maintainers:
    - beckermr
    - conda-forge/bot
""")
        assert not is_recipe_solvable(FEEDSTOCK_DIR)
    finally:
        try:
            os.remove(recipe_file)
        except Exception:
            pass


@pytest.mark.parametrize("inreq,outreq", [
    ("blah 1.1*", "blah 1.1.*"),
    ("blah * *_osx", "blah * *_osx"),
    ("blah 1.1", "blah 1.1.*"),
    ("blah =1.1", "blah 1.1.*"),
    ("blah * *_osx", "blah * *_osx"),
    ("blah 1.2 *_osx", "blah 1.2.* *_osx"),
    ("blah >=1.1", "blah >=1.1"),
    ("blah >=1.1|5|>=5,<10|19.0", "blah >=1.1|5.*|>=5,<10|19.0.*"),
    ("blah >=1.1|5| >=5 , <10 |19.0", "blah >=1.1|5.*|>=5,<10|19.0.*"),
])
def test_norm_spec(inreq, outreq):
    assert _norm_spec(inreq) == outreq
