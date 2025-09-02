import itertools
import json
import os
import re
import subprocess
from pathlib import Path

import networkx as nx
import pytest
import yaml

from conda_forge_tick.contexts import ClonedFeedstockContext
from conda_forge_tick.feedstock_parser import populate_feedstock_attributes
from conda_forge_tick.migrators import (
    MigrationYaml,
    Migrator,
    MiniMigrator,
    Replacement,
    Version,
)
from conda_forge_tick.migrators.migration_yaml import all_noarch
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import (
    frozen_to_json_friendly,
    parse_meta_yaml,
    parse_recipe_yaml,
)

sample_yaml_rebuild = """
{% set version = "1.3.2" %}

package:
  name: scipy
  version: {{ version }}

source:
  url: https://github.com/scipy/scipy/archive/v{{ version }}.tar.gz
  sha256: ac0937d29a3f93cc26737fdf318c09408e9a48adee1648a25d0cdce5647b8eb4
  patches:
    - gh10591.patch
    - relax_gmres_error_check.patch  # [aarch64]
    - skip_problematic_boost_test.patch  # [aarch64 or ppc64le]
    - skip_problematic_root_finding.patch  # [aarch64 or ppc64le]
    - skip_TestIDCTIVFloat_aarch64.patch  # [aarch64]
    - skip_white_tophat03.patch  # [aarch64 or ppc64le]
    # remove this patch when updating to 1.3.3
{% if version == "1.3.2" %}
    - scipy-1.3.2-bad-tests.patch  # [osx and py == 38]
    - gh11046.patch                # [ppc64le]
{% endif %}


build:
  number: 0
  skip: true  # [win or py2k]

requirements:
  build:
    - {{ compiler('fortran') }}
    - {{ compiler('c') }}
    - {{ compiler('cxx') }}
  host:
    - libblas
    - libcblas
    - liblapack
    - python
    - setuptools
    - cython
    - numpy
    - pip
  run:
    - python
    - {{ pin_compatible('numpy') }}

test:
  requires:
    - pytest
    - pytest-xdist
    - mpmath
{% if version == "1.3.2" %}
    - blas * netlib  # [ppc64le]
{% endif %}

about:
  home: http://www.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Scientific Library for Python
  description: |
    SciPy is a Python-based ecosystem of open-source software for mathematics,
    science, and engineering.
  doc_url: http://www.scipy.org/docs.html
  dev_url: https://github.com/scipy/scipy

extra:
  recipe-maintainers:
    - jakirkham
    - msarahan
    - rgommers
    - ocefpaf
    - beckermr
"""

updated_yaml_rebuild = """
{% set version = "1.3.2" %}

package:
  name: scipy
  version: {{ version }}

source:
  url: https://github.com/scipy/scipy/archive/v{{ version }}.tar.gz
  sha256: ac0937d29a3f93cc26737fdf318c09408e9a48adee1648a25d0cdce5647b8eb4
  patches:
    - gh10591.patch
    - relax_gmres_error_check.patch  # [aarch64]
    - skip_problematic_boost_test.patch  # [aarch64 or ppc64le]
    - skip_problematic_root_finding.patch  # [aarch64 or ppc64le]
    - skip_TestIDCTIVFloat_aarch64.patch  # [aarch64]
    - skip_white_tophat03.patch  # [aarch64 or ppc64le]
    # remove this patch when updating to 1.3.3
{% if version == "1.3.2" %}
    - scipy-1.3.2-bad-tests.patch  # [osx and py == 38]
    - gh11046.patch                # [ppc64le]
{% endif %}


build:
  number: 1
  skip: true  # [win or py2k]

requirements:
  build:
    - {{ compiler('fortran') }}
    - {{ compiler('c') }}
    - {{ compiler('cxx') }}
  host:
    - libblas
    - libcblas
    - liblapack
    - python
    - setuptools
    - cython
    - numpy
    - pip
  run:
    - python
    - {{ pin_compatible('numpy') }}

test:
  requires:
    - pytest
    - pytest-xdist
    - mpmath
{% if version == "1.3.2" %}
    - blas * netlib  # [ppc64le]
{% endif %}

about:
  home: http://www.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Scientific Library for Python
  description: |
    SciPy is a Python-based ecosystem of open-source software for mathematics,
    science, and engineering.
  doc_url: http://www.scipy.org/docs.html
  dev_url: https://github.com/scipy/scipy

extra:
  recipe-maintainers:
    - jakirkham
    - msarahan
    - rgommers
    - ocefpaf
    - beckermr
"""


updated_yaml_rebuild_no_build_number = """
{% set version = "1.3.2" %}

package:
  name: scipy
  version: {{ version }}

source:
  url: https://github.com/scipy/scipy/archive/v{{ version }}.tar.gz
  sha256: ac0937d29a3f93cc26737fdf318c09408e9a48adee1648a25d0cdce5647b8eb4
  patches:
    - gh10591.patch
    - relax_gmres_error_check.patch  # [aarch64]
    - skip_problematic_boost_test.patch  # [aarch64 or ppc64le]
    - skip_problematic_root_finding.patch  # [aarch64 or ppc64le]
    - skip_TestIDCTIVFloat_aarch64.patch  # [aarch64]
    - skip_white_tophat03.patch  # [aarch64 or ppc64le]
    # remove this patch when updating to 1.3.3
{% if version == "1.3.2" %}
    - scipy-1.3.2-bad-tests.patch  # [osx and py == 38]
    - gh11046.patch                # [ppc64le]
{% endif %}


build:
  number: 0
  skip: true  # [win or py2k]

requirements:
  build:
    - {{ compiler('fortran') }}
    - {{ compiler('c') }}
    - {{ compiler('cxx') }}
  host:
    - libblas
    - libcblas
    - liblapack
    - python
    - setuptools
    - cython
    - numpy
    - pip
  run:
    - python
    - {{ pin_compatible('numpy') }}

test:
  requires:
    - pytest
    - pytest-xdist
    - mpmath
{% if version == "1.3.2" %}
    - blas * netlib  # [ppc64le]
{% endif %}

about:
  home: http://www.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Scientific Library for Python
  description: |
    SciPy is a Python-based ecosystem of open-source software for mathematics,
    science, and engineering.
  doc_url: http://www.scipy.org/docs.html
  dev_url: https://github.com/scipy/scipy

extra:
  recipe-maintainers:
    - jakirkham
    - msarahan
    - rgommers
    - ocefpaf
    - beckermr
"""


class NoFilter:
    def filter(self, attrs, not_bad_str_start=""):
        return False


class _MigrationYaml(NoFilter, MigrationYaml):
    pass


TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
yaml_rebuild = _MigrationYaml(yaml_contents="{}", name="hi", total_graph=TOTAL_GRAPH)
yaml_rebuild.cycles = []
yaml_rebuild_no_build_number = _MigrationYaml(
    yaml_contents="{}",
    name="hi",
    bump_number=0,
    total_graph=TOTAL_GRAPH,
)
yaml_rebuild_no_build_number.cycles = []


def run_test_yaml_migration(
    m,
    *,
    inp,
    output,
    kwargs,
    prb,
    mr_out,
    tmp_path,
    should_filter=False,
    recipe_version: int = 0,
):
    recipe_path = tmp_path / "recipe"
    recipe_path.mkdir(exist_ok=True)
    with open(recipe_path / "meta.yaml", "w") as f:
        f.write(inp)

    with pushd(tmp_path):
        subprocess.run(["git", "init"])
    # Load the meta.yaml (this is done in the graph)
    try:
        if recipe_version == 0:
            pmy = parse_meta_yaml(inp)
        else:
            pmy = parse_recipe_yaml(inp)
    except Exception:
        pmy = {}
    if pmy:
        pmy["version"] = pmy["package"]["version"]
        pmy["req"] = set()
        for k in ["build", "host", "run"]:
            pmy["req"] |= set(pmy.get("requirements", {}).get(k, set()))
        try:
            pmy["meta_yaml"] = parse_meta_yaml(inp)
        except Exception:
            pmy["meta_yaml"] = {}
    pmy["raw_meta_yaml"] = inp
    pmy.update(kwargs)

    assert m.filter(pmy) is should_filter
    if should_filter:
        return

    mr = m.migrate(str(recipe_path), pmy)
    assert mr_out == mr
    pmy["pr_info"] = {}
    pmy["pr_info"].update(PRed=[frozen_to_json_friendly(mr)])
    with open(recipe_path / "meta.yaml") as f:
        actual_output = f.read()
    assert actual_output == output
    assert tmp_path.joinpath(".ci_support/migrations/hi.yaml").exists()
    with open(tmp_path / ".ci_support/migrations/hi.yaml") as f:
        saved_migration = f.read()
    assert saved_migration == m.yaml_contents


def test_yaml_migration_rebuild(tmp_path):
    run_test_yaml_migration(
        m=yaml_rebuild,
        inp=sample_yaml_rebuild,
        output=updated_yaml_rebuild,
        kwargs={"feedstock_name": "scipy"},
        prb="This PR has been triggered in an effort to update **hi**.",
        mr_out={
            "migrator_name": yaml_rebuild.__class__.__name__,
            "migrator_version": yaml_rebuild.migrator_version,
            "name": "hi",
            "bot_rerun": False,
        },
        tmp_path=tmp_path,
    )


def test_yaml_migration_rebuild_no_buildno(tmp_path):
    run_test_yaml_migration(
        m=yaml_rebuild_no_build_number,
        inp=sample_yaml_rebuild,
        output=updated_yaml_rebuild_no_build_number,
        kwargs={"feedstock_name": "scipy"},
        prb="This PR has been triggered in an effort to update **hi**.",
        mr_out={
            "migrator_name": yaml_rebuild.__class__.__name__,
            "migrator_version": yaml_rebuild.migrator_version,
            "name": "hi",
            "bot_rerun": False,
        },
        tmp_path=tmp_path,
    )


sample_matplotlib = """
{% set version = "0.9" %}

package:
  name: viscm
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/v/viscm/viscm-{{ version }}.tar.gz
  sha256: c770e4b76f726e653d2b7c2c73f71941a88de6eb47ccf8fb8e984b55562d05a2

build:
  number: 0
  noarch: python
  script: python -m pip install --no-deps --ignore-installed .

requirements:
  host:
    - python
    - pip
    - numpy
  run:
    - python
    - numpy
    - matplotlib
    - colorspacious

test:
  imports:
    - viscm

about:
  home: https://github.com/bids/viscm
  license: MIT
  license_file: LICENSE
  license_family: MIT
  # license_file: '' we need to an issue upstream to get a license in the source dist.
  summary: A colormap tool

extra:
  recipe-maintainers:
    - kthyng
"""

sample_matplotlib_correct = """
{% set version = "0.9" %}

package:
  name: viscm
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/v/viscm/viscm-{{ version }}.tar.gz
  sha256: c770e4b76f726e653d2b7c2c73f71941a88de6eb47ccf8fb8e984b55562d05a2

build:
  number: 1
  noarch: python
  script: python -m pip install --no-deps --ignore-installed .

requirements:
  host:
    - python
    - pip
    - numpy
  run:
    - python
    - numpy
    - matplotlib-base
    - colorspacious

test:
  imports:
    - viscm

about:
  home: https://github.com/bids/viscm
  license: MIT
  license_file: LICENSE
  license_family: MIT
  # license_file: '' we need to an issue upstream to get a license in the source dist.
  summary: A colormap tool

extra:
  recipe-maintainers:
    - kthyng
"""

version = Version(set(), total_graph=TOTAL_GRAPH)

matplotlib = Replacement(
    old_pkg="matplotlib",
    new_pkg="matplotlib-base",
    rationale=(
        "Unless you need `pyqt`, recipes should depend only on `matplotlib-base`."
    ),
    pr_limit=5,
    total_graph=TOTAL_GRAPH,
)


class MockLazyJson:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


os.environ["RUN_URL"] = "hi world"


def run_test_migration(
    m: Migrator,
    inp: str,
    output: str,
    kwargs: dict,
    prb: str,
    mr_out: dict,
    tmp_path: Path,
    should_filter: bool = False,
    make_body: bool = False,
    recipe_version: int = 0,
    conda_build_config: str | None = None,
):
    recipe_path = tmp_path / "recipe"

    if mr_out:
        mr_out.update(bot_rerun=False)

    recipe_path.mkdir(exist_ok=True)
    if recipe_version == 0:
        if conda_build_config:
            raise ValueError(
                "conda_build_config is only supported for recipe version 1 in this test function"
            )
        recipe_path.joinpath("meta.yaml").write_text(inp)
    elif recipe_version == 1:
        tmp_path.joinpath(".ci_support").mkdir()
        recipe_path.joinpath("recipe.yaml").write_text(inp)

        build_variants = (
            yaml.safe_load(conda_build_config) if conda_build_config else {}
        )

        if "target_platform" not in build_variants:
            build_variants["target_platform"] = ["linux-64", "osx-arm64", "win-64"]

        # move target_platform to the beginning of the keys
        build_variants = {
            "target_platform": build_variants.pop("target_platform"),
            **build_variants,
        }

        for assignment in itertools.product(*build_variants.values()):
            assignment_map = dict(zip(build_variants.keys(), assignment))
            variant_name = "_".join(
                str(value).replace("-", "_").replace("/", "")
                for value in assignment_map.values()
            )
            tmp_path.joinpath(f".ci_support/{variant_name}_.yaml").write_text(
                yaml.dump({k: [v] for k, v in assignment_map.items()})
            )
    else:
        raise ValueError(f"Unsupported recipe version: {recipe_version}")

    if conda_build_config:
        conda_build_config_file = recipe_path / "conda_build_config.yaml"
        conda_build_config_file.write_text(conda_build_config)
    else:
        conda_build_config_file = None

    # read the conda-forge.yml
    cf_yml_path = tmp_path / "conda-forge.yml"
    cf_yml = cf_yml_path.read_text() if cf_yml_path.exists() else "{}"

    # Load the meta.yaml (this is done in the graph)
    if recipe_version == 0:
        try:
            name = parse_meta_yaml(inp, cbc_path=conda_build_config_file)["package"][
                "name"
            ]
            if name is None:
                name = "blah"
        except Exception:
            name = "blah"

        pmy = populate_feedstock_attributes(
            name, existing_node_attrs={}, meta_yaml=inp, conda_forge_yaml=cf_yml
        )

        # these are here for legacy migrators
        pmy["version"] = pmy["meta_yaml"]["package"]["version"]
        pmy["req"] = set()
        for k in ["build", "host", "run"]:
            req = pmy["meta_yaml"].get("requirements", {}) or {}
            _set = req.get(k) or set()
            pmy["req"] |= set(_set)
        pmy["raw_meta_yaml"] = inp
        pmy.update(kwargs)
    else:
        try:
            name = parse_recipe_yaml(inp, cbc_path=conda_build_config_file)["package"][
                "name"
            ]
            if name is None:
                name = "blah"
        except Exception:
            name = "blah"

        pmy = populate_feedstock_attributes(
            name,
            existing_node_attrs={},
            recipe_yaml=inp,
            conda_forge_yaml=cf_yml,
            feedstock_dir=tmp_path,
        )
        pmy["version"] = pmy["meta_yaml"]["package"]["version"]
        pmy["raw_meta_yaml"] = inp

    if "new_version" in kwargs:
        pmy["version_pr_info"] = {"new_version": kwargs.pop("new_version")}

    pmy.update(kwargs)

    assert m.filter(pmy) == should_filter

    if should_filter:
        return pmy

    recipe_dir = str(recipe_path)
    m.run_pre_piggyback_migrations(
        recipe_dir,
        pmy,
        hash_type=pmy.get("hash_type", "sha256"),
    )
    mr = m.migrate(recipe_dir, pmy, hash_type=pmy.get("hash_type", "sha256"))
    m.run_post_piggyback_migrations(
        recipe_dir,
        pmy,
        hash_type=pmy.get("hash_type", "sha256"),
    )

    if make_body or prb:
        fctx = ClonedFeedstockContext(
            feedstock_name=name,
            attrs=pmy,
            local_clone_dir=tmp_path,
        )
        m.effective_graph.add_node(name)
        m.effective_graph.nodes[name]["payload"] = MockLazyJson({})
        prb_from_m = m.pr_body(fctx)
    else:
        prb_from_m = None

    assert mr_out == mr
    if not mr:
        return pmy

    pmy["pr_info"] = {}
    pmy["pr_info"].update(PRed=[frozen_to_json_friendly(mr)])
    if recipe_version == 0:
        actual_output = recipe_path.joinpath("meta.yaml").read_text()
    else:
        actual_output = recipe_path.joinpath("recipe.yaml").read_text()
    # strip jinja comments
    pat = re.compile(r"{#.*#}")
    actual_output = pat.sub("", actual_output)
    output = pat.sub("", output)

    assert actual_output == output

    if prb_from_m and prb:
        assert prb in prb_from_m

    assert m.filter(pmy) is True

    return pmy


def run_minimigrator(
    migrator: MiniMigrator,
    inp: str,
    output: str,
    mr_out: dict,
    tmp_path: Path,
    should_filter: bool = False,
):
    if mr_out:
        mr_out.update(bot_rerun=False)
    tmp_path.joinpath("recipe").mkdir()
    with open(tmp_path / "recipe/meta.yaml", "w") as f:
        f.write(inp)

    # read the conda-forge.yml
    if tmp_path.joinpath("conda-forge.yml").exists():
        with open(tmp_path / "conda-forge.yml") as fp:
            cf_yml = fp.read()
    else:
        cf_yml = "{}"

    # Load the meta.yaml (this is done in the graph)
    try:
        name = parse_meta_yaml(inp)["package"]["name"]
    except Exception:
        name = "blah"

    pmy = populate_feedstock_attributes(name, {}, inp, None, cf_yml)
    filtered = migrator.filter(pmy)
    if should_filter and filtered:
        return migrator
    assert filtered == should_filter

    with open(tmp_path / "recipe/meta.yaml") as f:
        actual_output = f.read()
    # strip jinja comments
    pat = re.compile(r"{#.*#}")
    actual_output = pat.sub("", actual_output)
    output = pat.sub("", output)
    assert actual_output == output


def test_generic_replacement(tmp_path):
    run_test_migration(
        m=matplotlib,
        inp=sample_matplotlib,
        output=sample_matplotlib_correct,
        kwargs={},
        prb="I noticed that this recipe depends on `matplotlib` instead of ",
        mr_out={
            "migrator_name": "Replacement",
            "migrator_version": matplotlib.migrator_version,
            "name": "matplotlib-to-matplotlib-base",
        },
        tmp_path=tmp_path,
    )


@pytest.mark.parametrize(
    "meta,is_all_noarch",
    [
        ({"build": {"noarch": "python"}}, True),
        ({"build": {"noarch": "generic"}}, True),
        ({"build": {"number": 1}}, False),
        ({"build": {}}, False),
        ({"build": None}, False),
        ({}, False),
        ({"build": {"noarch": "python"}, "outputs": [{"build": None}]}, True),
        ({"build": {"noarch": "generic"}, "outputs": [{"build": None}]}, True),
        ({"build": {"number": 1}, "outputs": [{"build": None}]}, False),
        ({"build": {}, "outputs": [{"build": None}]}, False),
        ({"build": None, "outputs": [{"build": None}]}, False),
        ({"outputs": [{"build": None}]}, False),
        ({"build": {"noarch": "python"}, "outputs": [{"build": {}}]}, True),
        ({"build": {"noarch": "generic"}, "outputs": [{"build": {}}]}, True),
        ({"build": {"number": 1}, "outputs": [{"build": {}}]}, False),
        ({"build": {}, "outputs": [{"build": {}}]}, False),
        ({"build": None, "outputs": [{"build": {}}]}, False),
        ({"outputs": [{"build": {}}]}, False),
        (
            {
                "build": {"noarch": "python"},
                "outputs": [{"build": {"noarch": "python"}}],
            },
            True,
        ),
        (
            {
                "build": {"noarch": "generic"},
                "outputs": [{"build": {"noarch": "python"}}],
            },
            True,
        ),
        ({"build": {"number": 1}, "outputs": [{"build": {"noarch": "python"}}]}, True),
        ({"build": {}, "outputs": [{"build": {"noarch": "python"}}]}, True),
        ({"build": None, "outputs": [{"build": {"noarch": "python"}}]}, True),
        ({"outputs": [{"build": {"noarch": "python"}}]}, True),
        (
            {
                "build": {"noarch": "python"},
                "outputs": [{"build": {"noarch": "generic"}}],
            },
            True,
        ),
        (
            {
                "build": {"noarch": "generic"},
                "outputs": [{"build": {"noarch": "generic"}}],
            },
            True,
        ),
        ({"build": {"number": 1}, "outputs": [{"build": {"noarch": "generic"}}]}, True),
        ({"build": {}, "outputs": [{"build": {"noarch": "generic"}}]}, True),
        ({"build": None, "outputs": [{"build": {"noarch": "generic"}}]}, True),
        ({"outputs": [{"build": {"noarch": "generic"}}]}, True),
    ],
)
def test_all_noarch(meta, is_all_noarch):
    attrs = {"meta_yaml": meta}
    assert all_noarch(attrs) == is_all_noarch


@pytest.mark.parametrize(
    "meta,is_all_noarch",
    [
        (
            json.loads(
                """\
{
  "about": {
   "description": "NetworkX is a Python language software package for the creation,\\nmanipulation, and study of the structure, dynamics, and functions of complex\\nnetworks.",
   "dev_url": "https://github.com/networkx/networkx",
   "doc_url": "https://networkx.org/documentation/stable/",
   "home": "https://networkx.org/",
   "license": "BSD-3-Clause",
   "license_family": "BSD-3-Clause",
   "license_file": "LICENSE.txt",
   "summary": "Python package for creating and manipulating complex networks"
  },
  "build": {
   "noarch": "python",
   "number": "2",
   "script": "${{ PYTHON }} -m pip install . -vv --no-deps --no-build-isolation"
  },
  "extra": {
   "recipe-maintainers": [
    "Schefflera-Arboricola",
    "stefanv",
    "synapticarbors",
    "ocefpaf",
    "SylvainCorlay",
    "FelixMoelder",
    "MridulS"
   ]
  },
  "outputs": [
   {
    "build": null,
    "name": "networkx",
    "requirements": {
     "build": [],
     "host": [
      "python ==3.10",
      "setuptools >=61.2",
      "pip"
     ],
     "run": [
      "python >=3.10"
     ]
    }
   }
  ],
  "package": {
   "name": "networkx",
   "version": "3.4.2"
  },
  "requirements": {
   "host": [
    "python ==3.10",
    "setuptools >=61.2",
    "pip"
   ],
   "run": [
    "python >=3.10"
   ]
  },
  "schema_version": 1,
  "source": {
   "sha256": "307c3669428c5362aab27c8a1260aa8f47c4e91d3891f48be0141738d8d053e1",
   "url": "https://pypi.org/packages/source/n/networkx/networkx-3.4.2.tar.gz"
  }
 }"""
            ),
            True,
        ),
        (
            json.loads(
                """\
{
  "about": {
   "description": "This is a python extension ",
   "dev_url": "https://github.com/esheldon/fitsio",
   "doc_url": "https://github.com/esheldon/fitsio",
   "home": "https://github.com/esheldon/fitsio",
   "license": "GPL-2.0-only AND Zlib",
   "license_file": [
    "LICENSE.txt",
    "LICENSE_cfitsio.txt",
    "LICENSE_zlib.txt"
   ],
   "summary": "A python library to read from and write to FITS files."
  },
  "build": {
   "ignore_run_exports_from": [
    "zlib"
   ],
   "number": "1"
  },
  "extra": {
   "recipe-maintainers": [
    "beckermr"
   ]
  },
  "package": {
   "name": "fitsio",
   "version": "1.2.4"
  },
  "requirements": {
   "build": [
    "libtool",
    "c_compiler_stub",
    "c_stdlib_stub",
    "make"
   ],
   "host": [
    "python",
    "pip",
    "setuptools",
    "numpy",
    "bzip2",
    "libcurl",
    "zlib"
   ],
   "run": [
    "python",
    "numpy",
    "bzip2",
    "setuptools"
   ]
  },
  "schema_version": 0,
  "source": {
   "sha256": "22bd17b87daee97b69a8c90e9bf5b10c43ba8f6c51c0d563c6d7fbe6dc6b622d",
   "url": "https://github.com/esheldon/fitsio/archive/refs/tags/1.2.4.tar.gz"
  },
  "test": {
   "commands": [
    "pytest --pyargs fitsio.tests"
   ],
   "imports": [
    "fitsio"
   ],
   "requires": [
    "pytest"
   ]
  }
 }"""
            ),
            False,
        ),
    ],
)
def test_all_noarch_python(meta, is_all_noarch):
    attrs = {"meta_yaml": meta}
    assert all_noarch(attrs, only_python=True) == is_all_noarch
