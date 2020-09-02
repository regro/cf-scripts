import os

from conda_forge_tick.audit import depfinder_audit_feedstock, grayskull_audit_feedstock
from conda_forge_tick.contexts import FeedstockContext, MigratorSessionContext
import networkx as nx

from conda_forge_tick.utils import load

DEPFINDER_RECIPE = """{% set name = "depfinder" %}
{% set version = 2.3.0 %}


package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/depfinder-{{ version }}.tar.gz
  sha256: 2694acbc8f7d94ca9bae55b8dc5b4860d5bc253c6a377b3b8ce63fb5bffa4000

build:
  number: 0
  noarch: python
  entry_points:
    - depfinder = depfinder.cli:cli
  script: {{ PYTHON }} -m pip install . -vv

requirements:
  host:
    - pip
    - python
  run:
    - python
    - pyyaml
    - stdlib-list

test:
  imports:
    - depfinder
  commands:
    - pip check
    - depfinder --help
  requires:
    - pip

about:
  home: http://github.com/ericdill/depfinder
  summary: Find all the imports in your library
  doc_url: https://pythonhosted.org/depfinder/
  license: BSD-3-Clause
  license_file: LICENSE

extra:
  recipe-maintainers:
    - ericdill
    - mariusvniekerk
    - tonyfast
    - ocefpaf
"""

# DEPFINDER_RECIPE = """{% set name = "depfinder" %}
# {% set version = 2.3.0 %}
#
#
# package:
#   name: {{ name|lower }}
#   version: {{ version }}
#
# source:
#   url: https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz
#   sha256: 2694acbc8f7d94ca9bae55b8dc5b4860d5bc253c6a377b3b8ce63fb5bffa4000
#
# build:
#   number: 0
#   noarch: python
#   script: {{ PYTHON }} -m pip install . -vv
#
# requirements:
#   host:
#     - pip
#     - python
#   run:
#     - python
#
# test:
#   imports:
#     - depfinder
#   commands:
#     - pip check
#   requires:
#     - pip
#
# about:
#   home: http://github.com/ericdill/depfinder
#   summary: Find all the imports in your library
#   doc_url: https://pythonhosted.org/depfinder/
#   license: BSD-3-Clause
#   license_file: LICENSE
#
# extra:
#   recipe-maintainers:
#     - ericdill
#     - mariusvniekerk
#     - tonyfast
#     - ocefpaf
# """

G = nx.DiGraph()
G.add_node("conda", reqs=["python"])


def test_depfinder_audit_feedstock():
    mm_ctx = MigratorSessionContext(
        graph=G,
        smithy_version="",
        pinning_version="",
        github_username="",
        github_password="",
        circle_build_url="",
    )
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"), "r",
    ) as f:
        attrs = load(f)
    fctx = FeedstockContext("depfinder", "depfinder", attrs)

    deps = depfinder_audit_feedstock(fctx, mm_ctx)
    assert deps == {
        "required": {"setuptools", "versioneer", "stdlib-list", "pyyaml"},
        "questionable": {"setuptools", "ipython", "ConfigParser", "cx_Freeze"},
        "builtin": {
            "errno",
            "__future__",
            "collections",
            "logging",
            "pprint",
            "pkgutil",
            "configparser",
            "os",
            "argparse",
            "subprocess",
            "pdb",
            "json",
            "io",
            "copy",
            "fnmatch",
            "ast",
            "distutils",
            "itertools",
            "re",
            "sys",
        },
        "relative": {"main", "_version"},
    }


def test_grayskull_audit_feedstock():
    mm_ctx = MigratorSessionContext(
        graph=G,
        smithy_version="",
        pinning_version="",
        github_username="",
        github_password="",
        circle_build_url="",
    )
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"), "r",
    ) as f:
        attrs = load(f)
    fctx = FeedstockContext("depfinder", "depfinder", attrs)

    recipe = grayskull_audit_feedstock(fctx, mm_ctx)
    assert recipe == DEPFINDER_RECIPE
