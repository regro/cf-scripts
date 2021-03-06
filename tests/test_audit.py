import os

from conda_forge_tick.contexts import FeedstockContext, MigratorSessionContext
import networkx as nx

from conda_forge_tick.utils import load
import pytest

DEPFINDER_RECIPE = """{% set name = "depfinder" %}
{% set version = "2.3.0" %}


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
"""  # noqa

G = nx.DiGraph()
G.add_node("conda", reqs=["python"])


@pytest.mark.skip(reason="fails on linux but not locally on osx")
def test_depfinder_audit_feedstock():
    from conda_forge_tick.audit import depfinder_audit_feedstock

    mm_ctx = MigratorSessionContext(
        graph=G,
        smithy_version="",
        pinning_version="",
        github_username="",
        github_password="",
        circle_build_url="",
    )
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    fctx = FeedstockContext("depfinder", "depfinder", attrs)

    deps = depfinder_audit_feedstock(fctx, mm_ctx)
    assert deps == {
        "builtin": {
            "ConfigParser",
            "__future__",
            "argparse",
            "ast",
            "collections",
            "configparser",
            "copy",
            "distutils.command.build_py",
            "distutils.command.sdist",
            "distutils.core",
            "errno",
            "fnmatch",
            "io",
            "itertools",
            "json",
            "logging",
            "os",
            "pdb",
            "pkgutil",
            "pprint",
            "re",
            "subprocess",
            "sys",
        },
        "questionable": {"setuptools", "ipython", "cx_freeze"},
        "required": {"pyyaml", "stdlib-list", "setuptools", "versioneer"},
    }


def test_grayskull_audit_feedstock():
    from conda_forge_tick.audit import grayskull_audit_feedstock

    mm_ctx = MigratorSessionContext(
        graph=G,
        smithy_version="",
        pinning_version="",
        github_username="",
        github_password="",
        circle_build_url="",
    )
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    fctx = FeedstockContext("depfinder", "depfinder", attrs)

    recipe = grayskull_audit_feedstock(fctx, mm_ctx)
    assert recipe == DEPFINDER_RECIPE
