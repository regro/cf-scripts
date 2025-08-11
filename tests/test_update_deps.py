import logging
import os
import tempfile
from pathlib import Path

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.lazy_json_backends import load
from conda_forge_tick.migrators import DependencyUpdateMigrator, Version
from conda_forge_tick.recipe_parser import CondaMetaYAML
from conda_forge_tick.update_deps import (
    DepComparison,
    _merge_dep_comparisons_sec,
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
    assert d["run"]["cf_minus_df"] == {"python <3.9"}
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

    d["run"]["df_minus_cf"].remove("pyyaml")
    recipe.meta["requirements"]["run"].append("pyyaml")
    updated_deps = _update_sec_deps(recipe, d, ["host", "run"], update_python=False)
    print("\n" + recipe.dumps())
    assert not updated_deps
    assert "python <3.9" in recipe.dumps()

    updated_deps = _update_sec_deps(recipe, d, ["host", "run"], update_python=True)
    print("\n" + recipe.dumps())
    assert updated_deps
    assert "python >=3.7" in recipe.dumps()


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
