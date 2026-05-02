import logging
import os
import tempfile
from pathlib import Path
from typing import Literal

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.lazy_json_backends import load
from conda_forge_tick.migrators import DependencyUpdateMigrator, Version
from conda_forge_tick.recipe_parser import CondaMetaYAML
from conda_forge_tick.update_deps import (
    DepComparison,
    _merge_dep_comparisons_sec,
    _modify_package_name_from_github,
    _update_sec_deps,
    apply_dep_update,
    generate_dep_hint,
    get_dep_updates_and_hints,
    get_depfinder_comparison,
    get_grayskull_comparison,
    make_grayskull_recipe,
)

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
VERSION = Version(
    set(),
    piggy_back_migrations=[DependencyUpdateMigrator(set())],
    total_graph=TOTAL_GRAPH,
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
    print(recipe, flush=True)
    assert recipe != ""
    assert attrs["version"] in recipe


def test_make_grayskull_recipe_github_url():
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "ngmix.json"),
    ) as f:
        attrs = load(f)
    recipe = make_grayskull_recipe(attrs)
    print(recipe, flush=True)
    assert recipe != ""
    assert attrs["version"] in recipe


def test_get_grayskull_comparison():
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    d, rs = get_grayskull_comparison(attrs)
    assert rs != ""
    assert d["run"]["cf_minus_df"] == {"python <3.9", "stdlib-list"}
    assert any(_d.startswith("python") for _d in d["run"]["df_minus_cf"])


def test_update_run_deps():
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    d, _ = get_grayskull_comparison(attrs)

    lines = attrs["raw_meta_yaml"].splitlines()
    lines = [ln + "\n" for ln in lines]
    recipe = CondaMetaYAML("".join(lines))

    recipe.meta["requirements"]["run"].append("pyyaml")
    updated_deps = _update_sec_deps(recipe, d, ["host", "run"], update_python=False)
    print("\n" + recipe.dumps())
    assert not updated_deps
    assert "python <3.9" in recipe.dumps()

    updated_deps = _update_sec_deps(recipe, d, ["host", "run"], update_python=True)
    print("\n" + recipe.dumps())
    assert updated_deps
    assert "python >={{ python_min }}" in recipe.dumps()


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
        print(d)
    assert d["run"] == {"df_minus_cf": {"pyyaml"}}
    assert "host" not in d


praw_recipe = """\
{% set name = "praw" %}
{% set import = "praw" %}
{% set version = "7.7.0" %}
{% set sha256 = "090d209b35f79dfa36082ed1cdaa0f9a753b9277a69cfe8f9f32fa1827411a5a" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  fn: {{ name }}-{{ version }}.tar.gz
  url: https://pypi.io/packages/source/{{ name[0]|lower }}/{{ name|lower }}/{{ name }}-{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  noarch: python
  number: 0
  script: {{ PYTHON }} -m pip install . --no-deps -vv

requirements:
  host:
    - python >=3.7
    - pip
  run:
    - python >=3.7
    - prawcore >=2.1,<3
    - update_checker >=0.18
    - websocket-client >=0.54.0

test:
  requires:
    - pip
  commands:
    - pip check
  imports:
    - {{ import }}

about:
  home: https://praw.readthedocs.io/
  license: BSD-2-Clause
  license_family: BSD
  license_file: LICENSE.txt
  summary: Python Reddit API Wrapper allows for simple access to Reddit's API
  description: |
    PRAW, an acronym for "Python Reddit API Wrapper", is a python package that
    allows for simple access to Reddit's API. PRAW aims to be easy to use and
    internally follows all of Reddit's API rules. With PRAW there's no need to
    introduce sleep calls in your code. Give your client an appropriate user
    agent and you're set.
  doc_url: https://praw.readthedocs.io/
  dev_url: https://github.com/praw-dev/praw

extra:
  recipe-maintainers:
    - CAM-Gerlach
    - djsutherland
"""


def test_get_dep_updates_and_hints_praw():
    attrs = {
        "name": "praw",
        "requirements": {
            "run": set(),
        },
        "new_version": "7.7.0",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        recipe = Path(tmpdir) / "meta.yaml"
        recipe.write_text(praw_recipe)

        res = get_dep_updates_and_hints(
            "hint",
            tmpdir,
            attrs,
            None,
            "new_version",
        )

    print(res[0], res[1], flush=True)
    assert "websocket" in res[1]


@pytest.mark.parametrize("disabled_param", ["disabled"])
def test_get_dep_updates_and_hints_disabled(disabled_param):
    dep_comparison, hints = get_dep_updates_and_hints(
        disabled_param, "RECIPE_DIR", {"no": "attrs"}, {"no_nodes"}, "VERSION_KEY"
    )

    assert dep_comparison == {}
    assert hints == ""


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
  script: "{{ PYTHON }} -m pip install . --no-deps -vv"
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
  script: "{{ PYTHON }} -m pip install . --no-deps -vv"
  entry_points:
    - depfinder = depfinder.cli:cli

requirements:
  host:
    # Python version is limited by stdlib-list.
    - python <3.9
    - pip
  run:
    - pyyaml
    - python <3.9
    - stdlib-list

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
  script: "{{ PYTHON }} -m pip install . --no-deps -vv"
  entry_points:
    - depfinder = depfinder.cli:cli

requirements:
  host:
    # Python version is limited by stdlib-list.
    - python <3.9
    - pip
  run:
    - pyyaml
    - python <3.9
    - stdlib-list

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
def test_update_deps_version(caplog, tmp_path, update_kind, out_yml):
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

    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
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


@pytest.mark.xfail()
@pytest.mark.parametrize(
    "update_kind,out_yml",
    [
        ("update-grayskull", out_yml_pyquil),
    ],
)
def test_update_deps_version_pyquil(caplog, tmp_path, update_kind, out_yml):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    new_ver = "3.1.0"

    kwargs = {
        "new_version": new_ver,
        "conda-forge.yml": {"bot": {"inspection": update_kind}},
    }

    run_test_migration(
        m=VERSION,
        inp=in_yml_pyquil,
        output=out_yml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
        make_body=True,
    )


@pytest.mark.parametrize(
    "recipe, dep_comparison, new_recipe",
    [
        (
            """schema_version: 1

context:
  name: azure-cli-core
  version: "2.75.0"

package:
  name: ${{ name|lower }}
  version: ${{ version }}

source:
  url: https://pypi.org/packages/source/${{ name[0] }}/${{ name }}/${{ name | replace('-', '_') }}-${{ version }}.tar.gz
  sha256: 0187f93949c806f8e39617cdb3b4fd4e3cac5ebe45f02dc0763850bcf7de8df2

build:
  number: 0
  noarch: python
  script: ${{ PYTHON }} -m pip install . --no-deps -vv

requirements:
  host:
    - python ${{ python_min }}.*
    - pip
    - setuptools
  run:
    - python >=${{ python_min }}
    - argcomplete >=3.5.2,<3.5.3
    - azure-cli-telemetry >=1.1.0
    - azure-mgmt-core >=1.2.0,<2
    - cryptography
    - distro
    - humanfriendly >=10.0
    - jmespath
    - knack >=0.11.0,<0.11.1
    - microsoft-security-utilities-secret-masker >=1.0.0b4,<1.1.0
    - msal ==1.33.0b1
    - msal_extensions ==1.2.0
    - packaging >=20.9
    - pkginfo >=1.5.0.1
    - psutil >=5.9
    - py-deviceid
    - pyjwt >=2.1.0
    - pyopenssl >=17.1.0
    - pysocks >=1.6.0
    - requests >=2.20.0

tests:
  - python:
      imports:
        - azure
        - azure.cli
        - azure.cli.core
        - azure.cli.core.commands
        - azure.cli.core.extension
        - azure.cli.core.profiles
      python_version: ${{ python_min }}.*

about:
  license: MIT
  license_file: LICENSE
  summary: Microsoft Azure Command-Line Tools Core Module
  homepage: https://github.com/Azure/azure-cli
  repository: https://github.com/Azure/azure-cli
  documentation: https://docs.microsoft.com/en-us/cli/azure

extra:
  recipe-maintainers:
    - dhirschfeld
    - andreyz4k
    - janjagusch""",
            {
                "host": {
                    "cf_minus_df": {"python 3.9.*", "setuptools"},
                    "df_minus_cf": {"python"},
                },
                "run": {
                    "cf_minus_df": {
                        "knack >=0.11.0,<0.11.1",
                        "pysocks >=1.6.0",
                        "azure-cli-telemetry >=1.1.0",
                        "python >=3.9",
                        "microsoft-security-utilities-secret-masker >=1.0.0b4,<1.1.0",
                        "humanfriendly >=10.0",
                        "argcomplete >=3.5.2,<3.5.3",
                        "requests >=2.20.0",
                        "msal_extensions ==1.2.0",
                    },
                    "df_minus_cf": {
                        "requests",
                        "knack >=0.11.0,<0.12.dev0",
                        "humanfriendly >=10.0,<11.dev0",
                        "argcomplete >=3.5.2,<3.6.dev0",
                        "microsoft-security-utilities-secret-masker >=1.0.0b4,<1.1.dev0",
                        "python",
                        "msal-extensions ==1.2.0",
                        "azure-cli-telemetry ==1.1.0.*",
                    },
                },
            },
            """schema_version: 1

context:
  name: azure-cli-core
  version: 2.75.0

package:
  name: ${{ name|lower }}
  version: ${{ version }}

source:
  url: https://pypi.org/packages/source/${{ name[0] }}/${{ name }}/${{ name | replace('-', '_') }}-${{ version }}.tar.gz
  sha256: 0187f93949c806f8e39617cdb3b4fd4e3cac5ebe45f02dc0763850bcf7de8df2

build:
  number: 0
  noarch: python
  script: ${{ PYTHON }} -m pip install . --no-deps -vv

requirements:
  host:
    - python ${{ python_min }}.*
    - pip
    - setuptools
  run:
    - python >=${{ python_min }}
    - argcomplete >=3.5.2,<3.6.dev0
    - azure-cli-telemetry ==1.1.0.*
    - azure-mgmt-core >=1.2.0,<2
    - cryptography
    - distro
    - humanfriendly >=10.0,<11.dev0
    - jmespath
    - knack >=0.11.0,<0.12.dev0
    - microsoft-security-utilities-secret-masker >=1.0.0b4,<1.1.dev0
    - msal ==1.33.0b1
    - packaging >=20.9
    - pkginfo >=1.5.0.1
    - psutil >=5.9
    - py-deviceid
    - pyjwt >=2.1.0
    - pyopenssl >=17.1.0
    - requests
    - msal-extensions ==1.2.0
tests:
  - python:
      imports:
        - azure
        - azure.cli
        - azure.cli.core
        - azure.cli.core.commands
        - azure.cli.core.extension
        - azure.cli.core.profiles
      python_version: ${{ python_min }}.*

about:
  license: MIT
  license_file: LICENSE
  summary: Microsoft Azure Command-Line Tools Core Module
  homepage: https://github.com/Azure/azure-cli
  repository: https://github.com/Azure/azure-cli
  documentation: https://docs.microsoft.com/en-us/cli/azure

extra:
  recipe-maintainers:
    - dhirschfeld
    - andreyz4k
    - janjagusch
""",
        )
    ],
)
def test_apply_dep_update_v1(
    recipe: str, dep_comparison: DepComparison, new_recipe: str, tmp_path: Path
):
    recipe_file = tmp_path / "recipe.yaml"
    recipe_file.write_text(recipe)
    apply_dep_update(tmp_path, dep_comparison=dep_comparison)
    assert recipe_file.read_text() == new_recipe


@pytest.mark.parametrize(
    "attrs, expected_dep_comparison",
    [
        (
            {
                "feedstock_name": "depfinder",
                "meta_yaml": {
                    "about": {
                        "home": "http://github.com/ericdill/depfinder",
                        "license": "BSD-3-Clause",
                        "license_file": "LICENSE",
                        "summary": "Find all the unique imports in your library",
                    },
                    "build": {
                        "entry_points": [
                            "depfinder = depfinder.cli:cli",
                            "depfinder = depfinder.cli:cli",
                            "depfinder = depfinder.cli:cli",
                        ],
                        "noarch": "python",
                        "number": "0",
                        "script": " -m pip install . --no-deps -vv",
                    },
                    "extra": {
                        "recipe-maintainers": [
                            "ericdill",
                            "mariusvniekerk",
                            "tonyfast",
                            "ocefpaf",
                            "ericdill",
                            "mariusvniekerk",
                            "tonyfast",
                            "ocefpaf",
                            "ericdill",
                            "mariusvniekerk",
                            "tonyfast",
                            "ocefpaf",
                        ]
                    },
                    "package": {"name": "depfinder", "version": "2.3.0"},
                    "requirements": {
                        "host": [
                            "python <3.9",
                            "pip",
                            "python <3.9",
                            "pip",
                            "python <3.9",
                            "pip",
                        ],
                        "run": [
                            "python <3.9",
                            "stdlib-list",
                            "python <3.9",
                            "stdlib-list",
                            "python <3.9",
                            "stdlib-list",
                        ],
                    },
                    "source": {
                        "sha256": "2694acbc8f7d94ca9bae55b8dc5b4860d5bc253c6a377b3b8ce63fb5bffa4000",
                        "url": "https://pypi.io/packages/source/d/depfinder/depfinder-2.3.0.tar.gz",
                    },
                    "test": {
                        "commands": ["depfinder -h", "depfinder -h", "depfinder -h"],
                        "imports": ["depfinder", "depfinder", "depfinder"],
                    },
                },
                "name": "depfinder",
                "raw_meta_yaml": '{% set version = "2.3.0" %}\n\npackage:\n  name: depfinder\n  version: {{ version }}\n\nsource:\n  url: https://pypi.io/packages/source/d/depfinder/depfinder-{{ version }}.tar.gz\n  sha256: 2694acbc8f7d94ca9bae55b8dc5b4860d5bc253c6a377b3b8ce63fb5bffa4000\n\nbuild:\n  number: 0\n  noarch: python\n  script: "{{ PYTHON }} -m pip install . --no-deps -vv"\n  entry_points:\n    - depfinder = depfinder.cli:cli\n\nrequirements:\n  host:\n    # Python version is limited by stdlib-list.\n    - python <3.9\n    - pip\n  run:\n    - python <3.9\n    - stdlib-list\n\ntest:\n  commands:\n    - depfinder -h\n  imports:\n    - depfinder\n\nabout:\n  home: http://github.com/ericdill/depfinder\n  license: BSD-3-Clause\n  license_file: LICENSE\n  summary: Find all the unique imports in your library\n\nextra:\n  recipe-maintainers:\n    - ericdill\n    - mariusvniekerk\n    - tonyfast\n    - ocefpaf\n',
                "total_requirements": {
                    "build": set(),
                    "host": {"python <3.9", "pip"},
                    "run": {"python <3.9", "stdlib-list"},
                    "test": set(),
                },
                "version": "2.3.0",
            },
            {
                "host": {
                    "cf_minus_df": {"python <3.9"},
                    "df_minus_cf": {"python {{ python_min }}.*"},
                },
                "run": {
                    "cf_minus_df": {"python <3.9", "stdlib-list"},
                    "df_minus_cf": {"python >={{ python_min }}"},
                },
            },
        ),
        (
            {
                "meta_yaml": {
                    "schema_version": 1,
                    "package": {
                        "name": "azure-mgmt-synapse",
                        "version": "1.0.0",
                    },
                    "build": {"noarch": "python"},
                },
                "feedstock_name": "azure-mgmt-synapse",
                "version_pr_info": {"version": "2.0.0"},
                "total_requirements": {
                    "build": set(),
                    "host": {"pip", "python"},
                    "run": {
                        "msrest >=0.5.0",
                        "azure-mgmt-core >=1.2.0,<2.0.0",
                        "python",
                        "numpy",
                    },
                    "test": {"pip"},
                },
            },
            {
                "host": {"cf_minus_df": set(), "df_minus_cf": set()},
                "run": {
                    "cf_minus_df": {"numpy", "msrest >=0.5.0"},
                    "df_minus_cf": {"azure-common >=1.1,<2.dev0", "msrest >=0.6.21"},
                },
            },
        ),
    ],
    ids=["depfinder", "azure-mgmt-synapse"],
)
def test_get_grayskull_comparison_full(
    attrs: dict, expected_dep_comparison: DepComparison
):
    dep_comparison: DepComparison = get_grayskull_comparison(attrs=attrs)[0]
    assert dep_comparison == expected_dep_comparison


UpdateKind = Literal["update-grayskull"]


@pytest.fixture
def conda_build_config() -> str:
    return 'python_min: ["3.9"]\n'


@pytest.mark.parametrize(
    "update_kind, original_recipe, new_version, expected_new_recipe",
    [
        (
            "update-grayskull",
            r"""
# yaml-language-server: $schema=https://raw.githubusercontent.com/prefix-dev/recipe-format/main/schema.json
schema_version: 1

context:
  version: "0.116.0"

package:
  name: fastapi
  version: ${{ version }}

source:
  url: https://pypi.org/packages/source/f/fastapi/fastapi-${{ version }}.tar.gz
  sha256: 80dc0794627af0390353a6d1171618276616310d37d24faba6648398e57d687a
  patches:
    # this ships a `bin/fastapi` which says to install `fastapi-cli`
    # but as this recipe already depends on `fastapi-cli`, it clobbers the working one
    - 0000-no-broken-cli.patch

build:
  number: 0
  noarch: python
  script:
    - ${{ PYTHON }} -m pip install . -vv --no-deps --no-build-isolation --disable-pip-version-check

requirements:
  host:
    - pdm-backend
    - pip
    - python ${{ python_min }}.*
  run:
    - python >=${{ python_min }}
    # [project.dependencies]
    - starlette >=0.40.0,<0.47.0
    - typing_extensions >=4.8.0
    - pydantic >=1.7.4,!=1.8,!=1.8.1,!=2.0.0,!=2.0.1,!=2.1.0,<3.0.0
    # [project.optional-dependencies.standard]
    - email_validator >=2.0.0
    - fastapi-cli >=0.0.8
    - httpx >=0.23.0
    - jinja2 >=3.1.5
    - python-multipart >=0.0.18
    - uvicorn-standard >=0.12.0

tests:
  - python:
      pip_check: true
      python_version: ${{ python_min }}.*
      imports:
        - fastapi
        - fastapi.dependencies
        - fastapi.middleware
        - fastapi.openapi
        - fastapi.security
  - requirements:
      run:
        - python ${{ python_min }}.*
    script:
      - fastapi --version
      - fastapi --help

about:
  license: MIT
  license_file: LICENSE
  summary: FastAPI framework, high performance, easy to learn, fast to code, ready for production
  homepage: https://github.com/fastapi/fastapi
  repository: https://github.com/fastapi/fastapi
  documentation: https://fastapi.tiangolo.com

extra:
  recipe-maintainers:
    - dhirschfeld
    - tiangolo
    - synapticarbors
    - bollwyvl
""".strip(),
            "0.116.1",
            r"""
# yaml-language-server: $schema=https://raw.githubusercontent.com/prefix-dev/recipe-format/main/schema.json
schema_version: 1

context:
  version: 0.116.1

package:
  name: fastapi
  version: ${{ version }}

source:
  url: https://pypi.org/packages/source/f/fastapi/fastapi-${{ version }}.tar.gz
  sha256: ed52cbf946abfd70c5a0dccb24673f0670deeb517a88b3544d03c2a6bf283143
  patches:
    # this ships a `bin/fastapi` which says to install `fastapi-cli`
    # but as this recipe already depends on `fastapi-cli`, it clobbers the working one
    - 0000-no-broken-cli.patch

build:
  number: 0
  noarch: python
  script:
    - ${{ PYTHON }} -m pip install . -vv --no-deps --no-build-isolation --disable-pip-version-check

requirements:
  host:
    - pdm-backend
    - pip
    - python ${{ python_min }}.*
  run:
    - python >=${{ python_min }}
    - starlette >=0.40.0,<0.48.0
    - typing_extensions >=4.8.0
    - pydantic >=1.7.4,!=1.8,!=1.8.1,!=2.0.0,!=2.0.1,!=2.1.0,<3.0.0
tests:
  - python:
      pip_check: true
      python_version: ${{ python_min }}.*
      imports:
        - fastapi
        - fastapi.dependencies
        - fastapi.middleware
        - fastapi.openapi
        - fastapi.security
  - requirements:
      run:
        - python ${{ python_min }}.*
    script:
      - fastapi --version
      - fastapi --help

about:
  license: MIT
  license_file: LICENSE
  summary: FastAPI framework, high performance, easy to learn, fast to code, ready for production
  homepage: https://github.com/fastapi/fastapi
  repository: https://github.com/fastapi/fastapi
  documentation: https://fastapi.tiangolo.com

extra:
  recipe-maintainers:
    - dhirschfeld
    - tiangolo
    - synapticarbors
    - bollwyvl
""".lstrip(),
        )
    ],
)
def test_update_deps_version_v1(
    update_kind: UpdateKind,
    original_recipe: str,
    new_version: str,
    expected_new_recipe: str,
    tmp_path: Path,
    conda_build_config: str,
):
    kwargs = {
        "new_version": new_version,
        "conda-forge.yml": {"bot": {"inspection": update_kind}},
    }
    run_test_migration(
        m=VERSION,
        inp=original_recipe,
        output=expected_new_recipe,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": new_version,
        },
        tmp_path=tmp_path,
        make_body=True,
        recipe_version=1,
        conda_build_config=conda_build_config,
    )


def test_jsii_package_name_resolution():
    """Test that we get the PyPI name instead of feedstock package name for Grayskull.

    The error was mentioned in:
    https://github.com/conda-forge/python-jsii-feedstock/pull/73#issuecomment-3569793931
    """
    src = {"url": "https://pypi.org/packages/source/j/jsii/jsii-1.119.0.tar.gz"}
    feedstock_package_name = "python-jsii"
    resolved_name = _modify_package_name_from_github(feedstock_package_name, src)

    assert resolved_name == "jsii"


def test_get_grayskull_comparison_v1_python_min_mismatch():
    """Test that get_grayskull_comparison works for v1 recipes using python_min.

    This test reproduces the issue where grayskull generates a recipe with
    `skip: match(python, "<3.10")` but the feedstock's variant config only has
    `python_min` (not `python`). When rattler-build tries to render the recipe,
    it skips all variants because the `python` variable is not set.

    See: https://github.com/conda-forge/dominodatalab-feedstock/pull/21
    """
    attrs = {
        "raw_meta_yaml": """\
schema_version: 1

context:
  name: dominodatalab
  version: 2.0.0

package:
  name: ${{ name|lower }}
  version: ${{ version }}

source:
  url: https://pypi.org/packages/source/${{ name[0] }}/${{ name }}/dominodatalab-${{ version }}.tar.gz
  sha256: 05d0f44a89bf0562413018f638839e31bdc108d6ed67869d5ccaceacf41ee237

build:
  number: 0
  noarch: python
  script: ${{ PYTHON }} -m pip install . -vv

requirements:
  host:
    - python ${{ python_min }}.*
    - pip
  run:
    - python >=${{ python_min }}
    - packaging ==23.2
    - requests >=2.4.2
    - beautifulsoup4 >=4.11,<5.dev0
    - polling2 >=0.5.0,<0.6.dev0
    - urllib3 >=1.26.19,<3
    - frozendict >=2.3,<3.dev0
    - python-dateutil >=2.8.2,<2.9.dev0
    - retry ==0.9.2
    - typing_extensions >=4.13.0,<4.14.dev0
tests:
  - python:
      imports:
        - domino
      python_version: ${{ python_min }}.*
  - requirements:
      run:
        - pip
        - python ${{ python_min }}.*
    script:
      - pip check

about:
  summary: Python bindings for the Domino API
  license: Apache-2.0
  license_file: LICENSE.txt
  homepage: https://github.com/dominodatalab/python-domino

extra:
  recipe-maintainers:
    - janjagusch
""",
        "meta_yaml": {
            "schema_version": 1,
            "package": {
                "name": "dominodatalab",
                "version": "1.4.7",
            },
            "source": {
                "url": "https://pypi.org/packages/source/d/dominodatalab/dominodatalab-1.4.7.tar.gz",
            },
            "build": {"noarch": "python"},
        },
        "feedstock_name": "dominodatalab",
        "version_pr_info": {"version": "2.0.0"},
        "total_requirements": {
            "build": set(),
            "host": {"pip", "python"},
            "run": {
                "python",
                "packaging",
                "requests >=2.4.2",
                "beautifulsoup4 >=4.11,<4.12",
                "polling2 >=0.5.0,<0.6",
                "urllib3 >=1.26.12,<1.27",
                "typing-extensions >=4.5.0",
                "frozendict >=2.3.4,<2.4",
                "python-dateutil >=2.8.2,<2.9",
                "retry ==0.9.2",
            },
            "test": set(),
        },
    }

    # This should not raise an exception, but currently it does because
    # grayskull generates `skip: match(python, "<3.10")` and the variant
    # config only has `python_min`, causing rattler-build to skip all variants.
    dep_comparison, recipe = get_grayskull_comparison(attrs=attrs)

    # If we get here, the comparison should have valid results
    assert "run" in dep_comparison
    assert recipe != ""
