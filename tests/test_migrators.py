import os
import re
import subprocess
from pathlib import Path

from conda_forge_tick.contexts import ClonedFeedstockContext
from conda_forge_tick.feedstock_parser import populate_feedstock_attributes
from conda_forge_tick.migrators import (
    MigrationYaml,
    Migrator,
    MiniMigrator,
    Replacement,
    Version,
)
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import frozen_to_json_friendly, parse_meta_yaml

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


yaml_rebuild = _MigrationYaml(yaml_contents="hello world", name="hi")
yaml_rebuild.cycles = []
yaml_rebuild_no_build_number = _MigrationYaml(
    yaml_contents="hello world",
    name="hi",
    bump_number=0,
)
yaml_rebuild_no_build_number.cycles = []


def run_test_yaml_migration(
    m, *, inp, output, kwargs, prb, mr_out, tmpdir, should_filter=False
):
    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    with open(os.path.join(tmpdir, "recipe", "meta.yaml"), "w") as f:
        f.write(inp)

    with pushd(tmpdir):
        subprocess.run(["git", "init"])
    # Load the meta.yaml (this is done in the graph)
    try:
        pmy = parse_meta_yaml(inp)
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

    mr = m.migrate(os.path.join(tmpdir, "recipe"), pmy)
    assert mr_out == mr
    pmy["pr_info"] = {}
    pmy["pr_info"].update(PRed=[frozen_to_json_friendly(mr)])
    with open(os.path.join(tmpdir, "recipe/meta.yaml")) as f:
        actual_output = f.read()
    assert actual_output == output
    assert os.path.exists(os.path.join(tmpdir, ".ci_support/migrations/hi.yaml"))
    with open(os.path.join(tmpdir, ".ci_support/migrations/hi.yaml")) as f:
        saved_migration = f.read()
    assert saved_migration == m.yaml_contents


def test_yaml_migration_rebuild(tmpdir):
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
        tmpdir=tmpdir,
    )


def test_yaml_migration_rebuild_no_buildno(tmpdir):
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
        tmpdir=tmpdir,
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

version = Version(set())

matplotlib = Replacement(
    old_pkg="matplotlib",
    new_pkg="matplotlib-base",
    rationale=(
        "Unless you need `pyqt`, recipes should depend only on " "`matplotlib-base`."
    ),
    pr_limit=5,
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
    tmpdir: str,
    should_filter: bool = False,
    make_body: bool = False,
):
    if mr_out:
        mr_out.update(bot_rerun=False)

    Path(tmpdir).joinpath("meta.yaml").write_text(inp)

    # read the conda-forge.yml
    cf_yml_path = Path(tmpdir).parent / "conda-forge.yml"
    cf_yml = cf_yml_path.read_text() if cf_yml_path.exists() else "{}"

    # Load the meta.yaml (this is done in the graph)
    try:
        name = parse_meta_yaml(inp)["package"]["name"]
    except Exception:
        name = "blah"

    pmy = populate_feedstock_attributes(
        name, sub_graph={}, meta_yaml=inp, conda_forge_yaml=cf_yml
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

    try:
        if "new_version" in kwargs:
            pmy["version_pr_info"] = {"new_version": kwargs["new_version"]}
        assert m.filter(pmy) == should_filter
    finally:
        pmy.pop("version_pr_info", None)
    if should_filter:
        return pmy

    m.run_pre_piggyback_migrations(
        tmpdir,
        pmy,
        hash_type=pmy.get("hash_type", "sha256"),
    )
    mr = m.migrate(tmpdir, pmy, hash_type=pmy.get("hash_type", "sha256"))
    m.run_post_piggyback_migrations(
        tmpdir,
        pmy,
        hash_type=pmy.get("hash_type", "sha256"),
    )

    if make_body:
        fctx = ClonedFeedstockContext(
            feedstock_name=name,
            attrs=pmy,
            local_clone_dir=Path(tmpdir),
        )
        m.effective_graph.add_node(name)
        m.effective_graph.nodes[name]["payload"] = MockLazyJson({})
        m.pr_body(fctx)

    assert mr_out == mr
    if not mr:
        return pmy

    pmy["pr_info"] = {}
    pmy["pr_info"].update(PRed=[frozen_to_json_friendly(mr)])
    with open(os.path.join(tmpdir, "meta.yaml")) as f:
        actual_output = f.read()
    # strip jinja comments
    pat = re.compile(r"{#.*#}")
    actual_output = pat.sub("", actual_output)
    output = pat.sub("", output)
    assert actual_output == output
    # TODO: fix subgraph here (need this to be xsh file)
    if isinstance(m, Version):
        pass
    else:
        assert prb in m.pr_body(None)
    try:
        if "new_version" in kwargs:
            pmy["version_pr_info"] = {"new_version": kwargs["new_version"]}
        assert m.filter(pmy) is True
    finally:
        pmy.pop("version_pr_info", None)

    return pmy


def run_minimigrator(
    migrator: MiniMigrator,
    inp: str,
    output: str,
    mr_out: dict,
    tmpdir: str,
    should_filter: bool = False,
):
    if mr_out:
        mr_out.update(bot_rerun=False)
    with open(os.path.join(tmpdir, "meta.yaml"), "w") as f:
        f.write(inp)

    # read the conda-forge.yml
    if os.path.exists(os.path.join(tmpdir, "..", "conda-forge.yml")):
        with open(os.path.join(tmpdir, "..", "conda-forge.yml")) as fp:
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

    with open(os.path.join(tmpdir, "meta.yaml")) as f:
        actual_output = f.read()
    # strip jinja comments
    pat = re.compile(r"{#.*#}")
    actual_output = pat.sub("", actual_output)
    output = pat.sub("", output)
    assert actual_output == output


def test_generic_replacement(tmpdir):
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
        tmpdir=tmpdir,
    )
