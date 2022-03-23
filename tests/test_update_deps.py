import os
import tempfile
import logging

from flaky import flaky

from conda_forge_tick.utils import load
from conda_forge_tick.recipe_parser import CondaMetaYAML
from conda_forge_tick.update_deps import (
    get_depfinder_comparison,
    get_grayskull_comparison,
    generate_dep_hint,
    make_grayskull_recipe,
    _update_sec_deps,
    _merge_dep_comparisons_sec,
)
from conda_forge_tick.migrators import Version, DependencyUpdateMigrator

import pytest

from test_migrators import run_test_migration


VERSION = Version(
    set(),
    piggy_back_migrations=[DependencyUpdateMigrator(set())],
)


@pytest.mark.parametrize(
    "dp1,dp2,m",
    [
        ({}, {}, {}),
        (
            {"df_minus_cf": {"a"}},
            {},
            {"df_minus_cf": {"a"}},
        ),
        (
            {},
            {"df_minus_cf": {"a"}},
            {"df_minus_cf": {"a"}},
        ),
        (
            {"df_minus_cf": {"a"}},
            {"cf_minus_df": {"b"}},
            {"df_minus_cf": {"a"}, "cf_minus_df": {"b"}},
        ),
        (
            {"df_minus_cf": {"a"}},
            {"df_minus_cf": {"c", "d"}, "cf_minus_df": {"b"}},
            {"df_minus_cf": {"a", "c", "d"}, "cf_minus_df": {"b"}},
        ),
        (
            {"df_minus_cf": {"c", "d"}, "cf_minus_df": {"b"}},
            {"df_minus_cf": {"a"}},
            {"df_minus_cf": {"a", "c", "d"}, "cf_minus_df": {"b"}},
        ),
        (
            {"df_minus_cf": {"a >=2"}},
            {"df_minus_cf": {"a"}},
            {"df_minus_cf": {"a >=2"}},
        ),
        (
            {"df_minus_cf": {"a"}},
            {"df_minus_cf": {"a >=2"}},
            {"df_minus_cf": {"a"}},
        ),
    ],
)
def test_merge_dep_comparisons(dp1, dp2, m):
    assert m == _merge_dep_comparisons_sec(dp1, dp2)


def test_generate_dep_hint():
    hint = generate_dep_hint({}, "blahblahblah")
    assert "no discrepancy" in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" not in hint
    assert "but not in the meta.yaml" not in hint

    df = {"run": {"df_minus_cf": {"a"}, "cf_minus_df": {"b"}}}
    hint = generate_dep_hint(df, "blahblahblah")
    assert "no discrepancy" not in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" in hint
    assert "but not in the meta.yaml" in hint

    df = {"host": {"df_minus_cf": {"a"}}}
    hint = generate_dep_hint(df, "blahblahblah")
    assert "no discrepancy" not in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" not in hint
    assert "but not in the meta.yaml" in hint

    df = {"run": {"cf_minus_df": {"b"}}, "host": {}}
    hint = generate_dep_hint(df, "blahblahblah")
    assert "no discrepancy" not in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" in hint
    assert "but not in the meta.yaml" not in hint


def test_make_grayskull_recipe():
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    recipe = make_grayskull_recipe(attrs)
    assert recipe != ""


def test_get_grayskull_comparison():
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    d, rs = get_grayskull_comparison(attrs)
    assert rs != ""
    assert d["run"]["cf_minus_df"] == {"python <3.9"}
    assert any(_d.startswith("python") for _d in d["run"]["df_minus_cf"])


def test_update_run_deps():
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    d, rs = get_grayskull_comparison(attrs)
    lines = attrs["raw_meta_yaml"].splitlines()
    lines = [ln + "\n" for ln in lines]
    recipe = CondaMetaYAML("".join(lines))

    updated_deps = _update_sec_deps(recipe, d, ["host", "run"], update_python=False)
    print("\n" + recipe.dumps())
    assert not updated_deps
    assert "python <3.9" in recipe.dumps()

    updated_deps = _update_sec_deps(recipe, d, ["host", "run"], update_python=True)
    print("\n" + recipe.dumps())
    assert updated_deps
    assert "python >=3.6" in recipe.dumps()


@flaky
def test_get_depfinder_comparison():
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)

    with tempfile.TemporaryDirectory() as tmpdir:
        pth = os.path.join(tmpdir, "meta.yaml")
        with open(pth, "w") as fp:
            fp.write(attrs["raw_meta_yaml"])

        d = get_depfinder_comparison(tmpdir, attrs, {"conda"})
    assert len(d["run"]) == 0
    assert "host" not in d


out_yml_gs = """\
{% set version = "2.3.0" %}

package:
  name: depfinder
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/d/depfinder/depfinder-{{ version }}.tar.gz
  sha256: 2694acbc8f7d94ca9bae55b8dc5b4860d5bc253c6a377b3b8ce63fb5bffa4000

build:
  number: 0
  noarch: python
  script: {{ PYTHON }} -m pip install . --no-deps -vv
  entry_points:
    - depfinder = depfinder.cli:cli

requirements:
  host:
    # Python version is limited by stdlib-list.
    - python <3.9
    - pip
  run:
    - python <3.9
    - stdlib-list
    - pyyaml

test:
  commands:
    - depfinder -h
  imports:
    - depfinder

about:
  home: http://github.com/ericdill/depfinder
  license: BSD-3-Clause
  license_file: LICENSE
  summary: Find all the unique imports in your library

extra:
  recipe-maintainers:
    - ericdill
    - mariusvniekerk
    - tonyfast
    - ocefpaf
"""


out_yml_all = """\
{% set version = "2.3.0" %}

package:
  name: depfinder
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/d/depfinder/depfinder-{{ version }}.tar.gz
  sha256: 2694acbc8f7d94ca9bae55b8dc5b4860d5bc253c6a377b3b8ce63fb5bffa4000

build:
  number: 0
  noarch: python
  script: {{ PYTHON }} -m pip install . --no-deps -vv
  entry_points:
    - depfinder = depfinder.cli:cli

requirements:
  host:
    # Python version is limited by stdlib-list.
    - python <3.9
    - pip
  run:
    - python <3.9
    - stdlib-list
    - pyyaml

test:
  commands:
    - depfinder -h
  imports:
    - depfinder

about:
  home: http://github.com/ericdill/depfinder
  license: BSD-3-Clause
  license_file: LICENSE
  summary: Find all the unique imports in your library

extra:
  recipe-maintainers:
    - ericdill
    - mariusvniekerk
    - tonyfast
    - ocefpaf
"""

out_yml_src = """\
{% set version = "2.3.0" %}

package:
  name: depfinder
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/d/depfinder/depfinder-{{ version }}.tar.gz
  sha256: 2694acbc8f7d94ca9bae55b8dc5b4860d5bc253c6a377b3b8ce63fb5bffa4000

build:
  number: 0
  noarch: python
  script: {{ PYTHON }} -m pip install . --no-deps -vv
  entry_points:
    - depfinder = depfinder.cli:cli

requirements:
  host:
    # Python version is limited by stdlib-list.
    - python <3.9
    - pip
  run:
    - python <3.9
    - stdlib-list
    - pyyaml

test:
  commands:
    - depfinder -h
  imports:
    - depfinder

about:
  home: http://github.com/ericdill/depfinder
  license: BSD-3-Clause
  license_file: LICENSE
  summary: Find all the unique imports in your library

extra:
  recipe-maintainers:
    - ericdill
    - mariusvniekerk
    - tonyfast
    - ocefpaf
"""


@flaky
@pytest.mark.parametrize(
    "update_kind,out_yml",
    [
        ("update-grayskull", out_yml_gs),
        ("update-all", out_yml_all),
        (
            "update-source",
            out_yml_src,
        ),
    ],
)
def test_update_deps_version(caplog, tmpdir, update_kind, out_yml):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)

    in_yaml = (
        attrs["raw_meta_yaml"].replace("2.3.0", "2.2.0").replace("2694acbc8f7", "")
    )
    new_ver = "2.3.0"

    kwargs = {
        "new_version": new_ver,
        "conda-forge.yml": {"bot": {"inspection": update_kind}},
    }

    os.makedirs(os.path.join(tmpdir, "recipe"))
    with open(os.path.join(tmpdir, "recipe", "meta.yaml"), "w") as fp:
        fp.write(in_yaml)

    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmpdir=os.path.join(tmpdir, "recipe"),
        make_body=True,
    )


in_yml_pyquil = """\
{% set name = "pyquil" %}
{% set version = "3.0.1" %}


package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/pyquil-{{ version }}.tar.gz
  sha256: 5d7f1414c8bcaec6b86577ca1a75a020b0315845eaf3165ae4c0d3633987a387

build:
  number: 0
  noarch: python
  script: {{ PYTHON }} -m pip install . -vv

requirements:
  host:
    - pip
    - poetry-core >=1.0.0
    - python >=3.7,<4.0
  run:
    - importlib-metadata >=3.7.3,<4.0.0
    - lark >=0.11.1,<0.12.0
    - networkx >=2.5,<3.0
    - numpy >=1.20,<2.0
    - python >=3.7,<4.0
    - qcs-api-client >=0.8.0,<0.9.0
    - retry >=0.9.2,<0.10.0
    - rpcq >=3.6.0,<4.0.0
    - scipy >=1.6.1,<2.0.0
  run_constrained:
    - ipython >=7.21.0,<8.0.0

test:
  imports:
    - pyquil
    - pyquil._parser
    - pyquil.gates
  commands:
    - pip check
  requires:
    - pip

about:
  home: http://forest.rigetti.com
  license: Apache-2.0
  license_family: Apache
  license_file: LICENSE
  summary: A Python library for quantum programming using Quil
  doc_url: http://pyquil.readthedocs.io/en/latest/
  dev_url: https://github.com/rigetticomputing/pyquil

extra:
  recipe-maintainers:
    - jmackeyrigetti
    - kilimanjaro
    - notmgsk
    - BastianZim
"""  # noqa

out_yml_pyquil = """\
{% set name = "pyquil" %}
{% set version = "3.1.0" %}


package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/{{ name[0] }}/{{ name }}/pyquil-{{ version }}.tar.gz
  sha256: 8ca8b67fe1cc4dcbee06a061edf876df1c2172edf21e979d4bf1e8c640616db3

build:
  number: 0
  noarch: python
  script: {{ PYTHON }} -m pip install . -vv

requirements:
  host:
    - pip
    - poetry-core >=1.0.0
    - python >=3.7,<4.0
  run:
    - importlib-metadata >=3.7.3,<4.0.0
    - lark >=0.11.1,<0.12.0
    - networkx >=2.5,<3.0
    - numpy >=1.20,<2.0
    - python >=3.7,<4.0
    - qcs-api-client >=0.8.1,<0.21.0
    - retry >=0.9.2,<0.10.0
    - rpcq >=3.6.0,<4.0.0
    - scipy >=1.6.1,<2.0.0
  run_constrained:
    - ipython >=7.21.0,<8.0.0

test:
  imports:
    - pyquil
    - pyquil._parser
    - pyquil.gates
  commands:
    - pip check
  requires:
    - pip

about:
  home: http://forest.rigetti.com
  license: Apache-2.0
  license_family: Apache
  license_file: LICENSE
  summary: A Python library for quantum programming using Quil
  doc_url: http://pyquil.readthedocs.io/en/latest/
  dev_url: https://github.com/rigetticomputing/pyquil

extra:
  recipe-maintainers:
    - jmackeyrigetti
    - kilimanjaro
    - notmgsk
    - BastianZim
"""  # noqa


@flaky
@pytest.mark.parametrize(
    "update_kind,out_yml",
    [
        ("update-grayskull", out_yml_pyquil),
    ],
)
def test_update_deps_version_pyquil(caplog, tmpdir, update_kind, out_yml):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    new_ver = "3.1.0"

    kwargs = {
        "new_version": new_ver,
        "conda-forge.yml": {"bot": {"inspection": update_kind}},
    }

    os.makedirs(os.path.join(tmpdir, "recipe"))
    with open(os.path.join(tmpdir, "recipe", "meta.yaml"), "w") as fp:
        fp.write(in_yml_pyquil)

    run_test_migration(
        m=VERSION,
        inp=in_yml_pyquil,
        output=out_yml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmpdir=os.path.join(tmpdir, "recipe"),
        make_body=True,
    )
