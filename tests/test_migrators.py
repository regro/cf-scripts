import os
import builtins
import re

import pytest
import networkx as nx

from conda_forge_tick.contexts import MigratorSessionContext, MigratorContext
from conda_forge_tick.migrators import (
    Version,
    MigrationYaml,
    Replacement,
)

# Legacy THINGS
from conda_forge_tick.migrators.disabled.legacy import (
    JS,
    Compiler,
    Noarch,
    Pinning,
    NoarchR,
    BlasRebuild,
    Rebuild,
)

from conda_forge_tick.utils import parse_meta_yaml, frozen_to_json_friendly
from conda_forge_tick.make_graph import populate_feedstock_attributes

from xonsh.lib import subprocess
from xonsh.lib.os import indir


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
    yaml_contents="hello world", name="hi", bump_number=0,
)
yaml_rebuild_no_build_number.cycles = []


def run_test_yaml_migration(
    m, *, inp, output, kwargs, prb, mr_out, tmpdir, should_filter=False
):
    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    with open(os.path.join(tmpdir, "recipe", "meta.yaml"), "w") as f:
        f.write(inp)

    with indir(tmpdir):
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

    pmy.update(PRed=[frozen_to_json_friendly(mr)])
    with open(os.path.join(tmpdir, "recipe/meta.yaml"), "r") as f:
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


sample_js = """{% set name = "jstz" %}
{% set version = "1.0.11" %}
{% set sha256 = "985d5fd8705930aab9cc59046e99c1f512d05109c9098039f880df5f5df2bf24" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://github.com/iansinnott/{{ name }}/archive/v{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  number: 0
  noarch: generic
  script: npm install -g .

requirements:
  build:
    - nodejs

test:
  commands:
    - npm list -g jstz
  requires:
    - nodejs


about:
  home: https://github.com/iansinnott/jstz
  license: MIT
  license_family: MIT
  license_file: LICENCE
  summary: 'Timezone detection for JavaScript'
  description: |
    This library allows you to detect a user's timezone from within their browser.
    It is often useful to use JSTZ in combination with a timezone parsing library
    such as Moment Timezone.
  doc_url: http://pellepim.bitbucket.org/jstz/
  dev_url: https://github.com/iansinnott/jstz

extra:
  recipe-maintainers:
    - cshaley
    - sannykr"""

sample_js2 = """{% set name = "jstz" %}
{% set version = "1.0.11" %}
{% set sha256 = "985d5fd8705930aab9cc59046e99c1f512d05109c9098039f880df5f5df2bf24" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://github.com/iansinnott/{{ name }}/archive/v{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  number: 0
  noarch: generic
   script: |
    tgz=$(npm pack)
    npm install -g $tgz

requirements:
  build:
    - nodejs

test:
  commands:
    - npm list -g jstz
  requires:
    - nodejs


about:
  home: https://github.com/iansinnott/jstz
  license: MIT
  license_family: MIT
  license_file: LICENCE
  summary: 'Timezone detection for JavaScript'
  description: |
    This library allows you to detect a user's timezone from within their browser.
    It is often useful to use JSTZ in combination with a timezone parsing library
    such as Moment Timezone.
  doc_url: http://pellepim.bitbucket.org/jstz/
  dev_url: https://github.com/iansinnott/jstz

extra:
  recipe-maintainers:
    - cshaley
    - sannykr"""

correct_js = """{% set name = "jstz" %}
{% set version = "1.0.11" %}
{% set sha256 = "985d5fd8705930aab9cc59046e99c1f512d05109c9098039f880df5f5df2bf24" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  url: https://github.com/iansinnott/{{ name }}/archive/v{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  number: 1
  noarch: generic
  script: |
    tgz=$(npm pack)
    npm install -g $tgz

requirements:
  build:
    - nodejs

test:
  commands:
    - npm list -g jstz
  requires:
    - nodejs


about:
  home: https://github.com/iansinnott/jstz
  license: MIT
  license_family: MIT
  license_file: LICENCE
  summary: 'Timezone detection for JavaScript'
  description: |
    This library allows you to detect a user's timezone from within their browser.
    It is often useful to use JSTZ in combination with a timezone parsing library
    such as Moment Timezone.
  doc_url: http://pellepim.bitbucket.org/jstz/
  dev_url: https://github.com/iansinnott/jstz

extra:
  recipe-maintainers:
    - cshaley
    - sannykr
"""

sample_cb3 = """
{# sample_cb3 #}
{% set version = "1.14.5" %}
{% set build_number = 0 %}

{% set variant = "openblas" %}
{% set build_number = build_number + 200 %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 1b4a02758fb68a65ea986d808867f1d6383219c234aef553a8741818e795b529

build:
  number: {{ build_number }}
  skip: true  # [win32 or (win and py27)]
  features:
    - blas_{{ variant }}

requirements:
  build:
    - python
    - pip
    - cython
    - toolchain
    - blas 1.1 {{ variant }}
    - openblas 0.2.20|0.2.20.*
  run:
    - python
    - blas 1.1 {{ variant }}
    - openblas 0.2.20|0.2.20.*

test:
  requires:
    - nose
  commands:
    - f2py -h
    - conda inspect linkages -p $PREFIX $PKG_NAME  # [not win]
    - conda inspect objects -p $PREFIX $PKG_NAME  # [osx]
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD 3-Clause
  license_file: LICENSE.txt
  summary: 'Array processing for numbers, strings, records, and objects.'
  doc_url: https://docs.scipy.org/doc/numpy/reference/
  dev_url: https://github.com/numpy/numpy

extra:
  recipe-maintainers:
    - jakirkham
    - msarahan
    - pelson
    - rgommers
    - ocefpaf
"""  # noqa

correct_cb3 = """
{# correct_cb3 #}
{% set version = "1.14.5" %}
{% set build_number = 1 %}

{% set variant = "openblas" %}
{% set build_number = build_number + 200 %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 1b4a02758fb68a65ea986d808867f1d6383219c234aef553a8741818e795b529

build:
  number: {{ build_number }}
  skip: true  # [win32 or (win and py27)]
  features:
    - blas_{{ variant }}

requirements:
  build:
    - {{ compiler('fortran') }}
    - {{ compiler('c') }}
    - {{ compiler('cxx') }}
  host:
    - python
    - pip
    - cython
    - blas 1.1 {{ variant }}
    - openblas
  run:
    - python
    - blas 1.1 {{ variant }}
    - openblas

test:
  requires:
    - nose
  commands:
    - f2py -h
    - conda inspect linkages -p $PREFIX $PKG_NAME  # [not win]
    - conda inspect objects -p $PREFIX $PKG_NAME  # [osx]
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD 3-Clause
  license_file: LICENSE.txt
  summary: 'Array processing for numbers, strings, records, and objects.'
  doc_url: https://docs.scipy.org/doc/numpy/reference/
  dev_url: https://github.com/numpy/numpy

extra:
  recipe-maintainers:
    - jakirkham
    - msarahan
    - pelson
    - rgommers
    - ocefpaf
"""  # noqa

sample_r_base = """
{# sample_r_base #}
{% set version = '0.7-1' %}

{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-stabledist
  version: {{ version|replace("-", "_") }}

source:
  fn: stabledist_{{ version }}.tar.gz
  url:
    - https://cran.r-project.org/src/contrib/stabledist_{{ version }}.tar.gz
    - https://cran.r-project.org/src/contrib/Archive/stabledist/stabledist_{{ version }}.tar.gz


  sha256: 06c5704d3a3c179fa389675c537c39a006867bc6e4f23dd7e406476ed2c88a69

build:
  number: 1

  rpaths:
    - lib/R/lib/
    - lib/
  skip: True  # [win32]

requirements:
  build:
    - r-base

  run:
    - r-base

test:
  commands:
    - $R -e "library('stabledist')"  # [not win]
    - "\\"%R%\\" -e \\"library('stabledist')\\""  # [win]
"""  # noqa

updated_r_base = """
{# updated_r_base #}
{% set version = '0.7-1' %}

{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-stabledist
  version: {{ version|replace("-", "_") }}

source:
  fn: stabledist_{{ version }}.tar.gz
  url:
    - https://cran.r-project.org/src/contrib/stabledist_{{ version }}.tar.gz
    - https://cran.r-project.org/src/contrib/Archive/stabledist/stabledist_{{ version }}.tar.gz


  sha256: 06c5704d3a3c179fa389675c537c39a006867bc6e4f23dd7e406476ed2c88a69

build:
  noarch: generic
  number: 2

  rpaths:
    - lib/R/lib/
    - lib/

requirements:
  build:
    - r-base

  run:
    - r-base

test:
  commands:
    - $R -e "library('stabledist')"  # [not win]
    - "\\"%R%\\" -e \\"library('stabledist')\\""  # [win]
"""  # noqa


sample_r_base2 = """
{% set version = '0.7-1' %}

{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-stabledist
  version: {{ version|replace("-", "_") }}

source:
  fn: stabledist_{{ version }}.tar.gz
  url:
    - https://cran.r-project.org/src/contrib/stabledist_{{ version }}.tar.gz
    - https://cran.r-project.org/src/contrib/Archive/stabledist/stabledist_{{ version }}.tar.gz


  sha256: 06c5704d3a3c179fa389675c537c39a006867bc6e4f23dd7e406476ed2c88a69

build:
  number: 1

  rpaths:
    - lib/R/lib/
    - lib/
  skip: True  # [win32]

requirements:
  build:
    - r-base
    - {{ compiler('c') }}

  run:
    - r-base

test:
  commands:
    - $R -e "library('stabledist')"  # [not win]
    - "\\"%R%\\" -e \\"library('stabledist')\\""  # [win]
"""  # noqa

updated_r_base2 = """
{% set version = '0.7-1' %}

{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-stabledist
  version: {{ version|replace("-", "_") }}

source:
  fn: stabledist_{{ version }}.tar.gz
  url:
    - https://cran.r-project.org/src/contrib/stabledist_{{ version }}.tar.gz
    - https://cran.r-project.org/src/contrib/Archive/stabledist/stabledist_{{ version }}.tar.gz


  sha256: 06c5704d3a3c179fa389675c537c39a006867bc6e4f23dd7e406476ed2c88a69

build:
  number: 2

  rpaths:
    - lib/R/lib/
    - lib/
  skip: True  # [win32]

requirements:
  build:
    - r-base
    - {{ compiler('c') }}

  run:
    - r-base

test:
  commands:
    - $R -e "library('stabledist')"  # [not win]
    - "\\"%R%\\" -e \\"library('stabledist')\\""  # [win]
"""  # noqa

# Test that filepaths to various licenses are updated for a noarch recipe
sample_r_licenses_noarch = """
{% set version = '0.7-1' %}

{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-stabledist
  version: {{ version|replace("-", "_") }}

source:
  fn: stabledist_{{ version }}.tar.gz
  url:
    - https://cran.r-project.org/src/contrib/stabledist_{{ version }}.tar.gz
    - https://cran.r-project.org/src/contrib/Archive/stabledist/stabledist_{{ version }}.tar.gz


  sha256: 06c5704d3a3c179fa389675c537c39a006867bc6e4f23dd7e406476ed2c88a69

build:
  number: 1

  rpaths:
    - lib/R/lib/
    - lib/
  skip: True  # [win32]

requirements:
  build:
    - r-base

  run:
    - r-base

test:
  commands:
    - $R -e "library('stabledist')"  # [not win]
    - "\\"%R%\\" -e \\"library('stabledist')\\""  # [win]

about:
  license_family: GPL3
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\\R\\share\\licenses\\GPL-3'  # [win]
  license_family: MIT
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/MIT'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\\R\\share\\licenses\\MIT'  # [win]
  license_family: LGPL
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/LGPL-2'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\\R\\share\\licenses\\LGPL-2'  # [win]
  license_family: LGPL
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/LGPL-2.1'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\\R\\share\\licenses\\LGPL-2.1'  # [win]
  license_family: BSD
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/BSD_3_clause'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\\R\\share\\licenses\\BSD_3_clause'  # [win]

  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2'  # [unix]
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/BSD_3_clause'  # [unix]
"""  # noqa

updated_r_licenses_noarch = """
{% set version = '0.7-1' %}

{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-stabledist
  version: {{ version|replace("-", "_") }}

source:
  fn: stabledist_{{ version }}.tar.gz
  url:
    - https://cran.r-project.org/src/contrib/stabledist_{{ version }}.tar.gz
    - https://cran.r-project.org/src/contrib/Archive/stabledist/stabledist_{{ version }}.tar.gz


  sha256: 06c5704d3a3c179fa389675c537c39a006867bc6e4f23dd7e406476ed2c88a69

build:
  noarch: generic
  number: 2

  rpaths:
    - lib/R/lib/
    - lib/

requirements:
  build:
    - r-base

  run:
    - r-base

test:
  commands:
    - $R -e "library('stabledist')"  # [not win]
    - "\\"%R%\\" -e \\"library('stabledist')\\""  # [win]

about:
  license_family: GPL3
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3'
  license_family: MIT
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/MIT'
  license_family: LGPL
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/LGPL-2'
  license_family: LGPL
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/LGPL-2.1'
  license_family: BSD
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/BSD_3_clause'

  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2'
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/BSD_3_clause'
"""  # noqa

# Test that filepaths to various licenses are updated for a compiled recipe
sample_r_licenses_compiled = """
{% set version = '0.7-1' %}

{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-stabledist
  version: {{ version|replace("-", "_") }}

source:
  fn: stabledist_{{ version }}.tar.gz
  url:
    - https://cran.r-project.org/src/contrib/stabledist_{{ version }}.tar.gz
    - https://cran.r-project.org/src/contrib/Archive/stabledist/stabledist_{{ version }}.tar.gz


  sha256: 06c5704d3a3c179fa389675c537c39a006867bc6e4f23dd7e406476ed2c88a69

build:
  number: 1

  rpaths:
    - lib/R/lib/
    - lib/
  skip: True  # [win32]

requirements:
  build:
    - r-base
    - {{ compiler('c') }}

  run:
    - r-base

test:
  commands:
    - $R -e "library('stabledist')"  # [not win]
    - "\\"%R%\\" -e \\"library('stabledist')\\""  # [win]

about:
  license_family: GPL3
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\\R\\share\\licenses\\GPL-3'  # [win]
  license_family: MIT
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/MIT'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\\R\\share\\licenses\\MIT'  # [win]
  license_family: LGPL
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/LGPL-2'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\\R\\share\\licenses\\LGPL-2'  # [win]
  license_family: LGPL
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/LGPL-2.1'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\\R\\share\\licenses\\LGPL-2.1'  # [win]
  license_family: BSD
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/BSD_3_clause'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\\R\\share\\licenses\\BSD_3_clause'  # [win]

  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2'  # [unix]
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/BSD_3_clause'  # [unix]
"""  # noqa

updated_r_licenses_compiled = """
{% set version = '0.7-1' %}

{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-stabledist
  version: {{ version|replace("-", "_") }}

source:
  fn: stabledist_{{ version }}.tar.gz
  url:
    - https://cran.r-project.org/src/contrib/stabledist_{{ version }}.tar.gz
    - https://cran.r-project.org/src/contrib/Archive/stabledist/stabledist_{{ version }}.tar.gz


  sha256: 06c5704d3a3c179fa389675c537c39a006867bc6e4f23dd7e406476ed2c88a69

build:
  number: 2

  rpaths:
    - lib/R/lib/
    - lib/
  skip: True  # [win32]

requirements:
  build:
    - r-base
    - {{ compiler('c') }}

  run:
    - r-base

test:
  commands:
    - $R -e "library('stabledist')"  # [not win]
    - "\\"%R%\\" -e \\"library('stabledist')\\""  # [win]

about:
  license_family: GPL3
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3'
  license_family: MIT
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/MIT'
  license_family: LGPL
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/LGPL-2'
  license_family: LGPL
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/LGPL-2.1'
  license_family: BSD
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/BSD_3_clause'

  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2'
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/BSD_3_clause'
"""  # noqa

sample_noarch = """
{# sample_noarch #}
{% set name = "xpdan" %}
{% set version = "0.3.3" %}
{% set sha256 = "3f1a84f35471aa8e383da3cf4436492d0428da8ff5b02e11074ff65d400dd076" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  fn: {{ name }}-{{ version }}.tar.gz
  url: https://github.com/xpdAcq/{{ name }}/releases/download/{{ version }}/{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  number: 0
  script: python -m pip install --no-deps --ignore-installed .

requirements:
  build:
    - python >=3
    - pip
  run:
    - python >=3
    - numpy
    - scipy
    - matplotlib
    - pyyaml
    - scikit-beam
    - pyfai
    - pyxdameraulevenshtein
    - xray-vision
    - databroker
    - bluesky
    - streamz_ext
    - xpdsim
    - shed
    - xpdview
    - ophyd
    - xpdconf

test:
  imports:
    - xpdan
    - xpdan.pipelines

about:
  home: http://github.com/xpdAcq/xpdAn
  license: BSD-3-Clause
  license_family: BSD
  license_file: LICENSE
  summary: 'Analysis Tools for XPD'
  doc_url: http://xpdacq.github.io/xpdAn/
  dev_url: http://github.com/xpdAcq/xpdAn

extra:
  recipe-maintainers:
    - CJ-Wright
"""  # noqa


updated_noarch = """
{# updated_noarch #}
{% set name = "xpdan" %}
{% set version = "0.3.3" %}
{% set sha256 = "3f1a84f35471aa8e383da3cf4436492d0428da8ff5b02e11074ff65d400dd076" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  fn: {{ name }}-{{ version }}.tar.gz
  url: https://github.com/xpdAcq/{{ name }}/releases/download/{{ version }}/{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  noarch: python
  number: 1
  script: python -m pip install --no-deps --ignore-installed .

requirements:
  host:
    - python >=3
    - pip
  run:
    - python >=3
    - numpy
    - scipy
    - matplotlib
    - pyyaml
    - scikit-beam
    - pyfai
    - pyxdameraulevenshtein
    - xray-vision
    - databroker
    - bluesky
    - streamz_ext
    - xpdsim
    - shed
    - xpdview
    - ophyd
    - xpdconf

test:
  imports:
    - xpdan
    - xpdan.pipelines

about:
  home: http://github.com/xpdAcq/xpdAn
  license: BSD-3-Clause
  license_family: BSD
  license_file: LICENSE
  summary: 'Analysis Tools for XPD'
  doc_url: http://xpdacq.github.io/xpdAn/
  dev_url: http://github.com/xpdAcq/xpdAn

extra:
  recipe-maintainers:
    - CJ-Wright
"""  # noqa

sample_noarch_space = """
{# sample_noarch_space #}
{% set name = "xpdan" %}
{% set version = "0.3.3" %}
{% set sha256 = "3f1a84f35471aa8e383da3cf4436492d0428da8ff5b02e11074ff65d400dd076" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  fn: {{ name }}-{{ version }}.tar.gz
  url: https://github.com/xpdAcq/{{ name }}/releases/download/{{ version }}/{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
    number: 0
    script: python -m pip install --no-deps --ignore-installed .

requirements:
  build:
    - python >=3
    - pip
  run:
    - python >=3
    - numpy
    - scipy
    - matplotlib
    - pyyaml
    - scikit-beam
    - pyfai
    - pyxdameraulevenshtein
    - xray-vision
    - databroker
    - bluesky
    - streamz_ext
    - xpdsim
    - shed
    - xpdview
    - ophyd
    - xpdconf

test:
  imports:
    - xpdan
    - xpdan.pipelines

about:
  home: http://github.com/xpdAcq/xpdAn
  license: BSD-3-Clause
  license_family: BSD
  license_file: LICENSE
  summary: 'Analysis Tools for XPD'
  doc_url: http://xpdacq.github.io/xpdAn/
  dev_url: http://github.com/xpdAcq/xpdAn

extra:
  recipe-maintainers:
    - CJ-Wright
"""  # noqa


updated_noarch_space = """
{# updated_noarch_space #}
{% set name = "xpdan" %}
{% set version = "0.3.3" %}
{% set sha256 = "3f1a84f35471aa8e383da3cf4436492d0428da8ff5b02e11074ff65d400dd076" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  fn: {{ name }}-{{ version }}.tar.gz
  url: https://github.com/xpdAcq/{{ name }}/releases/download/{{ version }}/{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
    noarch: python
    number: 1
    script: python -m pip install --no-deps --ignore-installed .

requirements:
  host:
    - python >=3
    - pip
  run:
    - python >=3
    - numpy
    - scipy
    - matplotlib
    - pyyaml
    - scikit-beam
    - pyfai
    - pyxdameraulevenshtein
    - xray-vision
    - databroker
    - bluesky
    - streamz_ext
    - xpdsim
    - shed
    - xpdview
    - ophyd
    - xpdconf

test:
  imports:
    - xpdan
    - xpdan.pipelines

about:
  home: http://github.com/xpdAcq/xpdAn
  license: BSD-3-Clause
  license_family: BSD
  license_file: LICENSE
  summary: 'Analysis Tools for XPD'
  doc_url: http://xpdacq.github.io/xpdAn/
  dev_url: http://github.com/xpdAcq/xpdAn

extra:
  recipe-maintainers:
    - CJ-Wright
"""  # noqa


sample_pinning = """
{# sample_pinning #}
{% set version = "2.44_01" %}

package:
  name: perl-xml-parser
  version: {{ version }}

source:
  fn: XML-Parser-{{ version }}.tar.gz
  url: https://cpan.metacpan.org/authors/id/T/TO/TODDR/XML-Parser-{{ version }}.tar.gz
  sha256: 5310ea5c8c707f387589bba8934ab9112463a452f828adf2755792d968b9ac7e

build:
  number: 0
  skip: True  # [win]

requirements:
  build:
    - toolchain3
    - perl 5.22.2.1
    - expat 2.2.*
  run:
    - perl 5.22.2.1
    - perl-xml-parser
    - expat 2.2.*

test:
  imports:
    - XML::Parser
    - XML::Parser::Expat
    - XML::Parser::Style::Debug
    - XML::Parser::Style::Objects
    - XML::Parser::Style::Stream
    - XML::Parser::Style::Subs
    - XML::Parser::Style::Tree

about:
  home: https://metacpan.org/pod/XML::Parser
  # According to http://dev.perl.org/licenses/ Perl5 is licensed either under
  # GPL v1 or later or the Artistic License
  license: GPL-3.0
  license_family: GPL
  summary: A perl module for parsing XML documents

extra:
  recipe-maintainers:
    - kynan
"""


updated_perl = """
{# updated_perl #}
{% set version = "2.44_01" %}

package:
  name: perl-xml-parser
  version: {{ version }}

source:
  fn: XML-Parser-{{ version }}.tar.gz
  url: https://cpan.metacpan.org/authors/id/T/TO/TODDR/XML-Parser-{{ version }}.tar.gz
  sha256: 5310ea5c8c707f387589bba8934ab9112463a452f828adf2755792d968b9ac7e

build:
  number: 1
  skip: True  # [win]

requirements:
  build:
    - toolchain3
    - perl
    - expat 2.2.*
  run:
    - perl
    - perl-xml-parser
    - expat 2.2.*

test:
  imports:
    - XML::Parser
    - XML::Parser::Expat
    - XML::Parser::Style::Debug
    - XML::Parser::Style::Objects
    - XML::Parser::Style::Stream
    - XML::Parser::Style::Subs
    - XML::Parser::Style::Tree

about:
  home: https://metacpan.org/pod/XML::Parser
  # According to http://dev.perl.org/licenses/ Perl5 is licensed either under
  # GPL v1 or later or the Artistic License
  license: GPL-3.0
  license_family: GPL
  summary: A perl module for parsing XML documents

extra:
  recipe-maintainers:
    - kynan
"""


updated_pinning = """
{# updated_pinning #}
{% set version = "2.44_01" %}

package:
  name: perl-xml-parser
  version: {{ version }}

source:
  fn: XML-Parser-{{ version }}.tar.gz
  url: https://cpan.metacpan.org/authors/id/T/TO/TODDR/XML-Parser-{{ version }}.tar.gz
  sha256: 5310ea5c8c707f387589bba8934ab9112463a452f828adf2755792d968b9ac7e

build:
  number: 1
  skip: True  # [win]

requirements:
  build:
    - toolchain3
    - perl
    - expat
  run:
    - perl
    - perl-xml-parser
    - expat

test:
  imports:
    - XML::Parser
    - XML::Parser::Expat
    - XML::Parser::Style::Debug
    - XML::Parser::Style::Objects
    - XML::Parser::Style::Stream
    - XML::Parser::Style::Subs
    - XML::Parser::Style::Tree

about:
  home: https://metacpan.org/pod/XML::Parser
  # According to http://dev.perl.org/licenses/ Perl5 is licensed either under
  # GPL v1 or later or the Artistic License
  license: GPL-3.0
  license_family: GPL
  summary: A perl module for parsing XML documents

extra:
  recipe-maintainers:
    - kynan
"""


sample_blas = """
{# sample_blas #}
{% set version = "1.2.1" %}
{% set variant = "openblas" %}

package:
  name: scipy
  version: {{ version }}

source:
  url: https://github.com/scipy/scipy/archive/v{{ version }}.tar.gz
  sha256: d4b9c1c1dee37ffd1653fd62ea52587212d3b1570c927f16719fd7c4077c0d0a

build:
  number: 0
  skip: true  # [win]
  features:
    - blas_{{ variant }}

requirements:
  build:
    - {{ compiler('fortran') }}
    - {{ compiler('c') }}
    - {{ compiler('cxx') }}
  host:
    - python
    - setuptools
    - cython
    - blas 1.1 {{ variant }}
    - openblas
    - numpy
  run:
    - python
    - blas 1.1 {{ variant }}
    - openblas
    - {{ pin_compatible('numpy') }}

test:
  requires:
    - pytest
    - mpmath
"""


updated_blas = """
{# updated_blas #}
{% set version = "1.2.1" %}

package:
  name: scipy
  version: {{ version }}

source:
  url: https://github.com/scipy/scipy/archive/v{{ version }}.tar.gz
  sha256: d4b9c1c1dee37ffd1653fd62ea52587212d3b1570c927f16719fd7c4077c0d0a

build:
  number: 1
  skip: true  # [win]
  features:

requirements:
  build:
    - {{ compiler('fortran') }}
    - {{ compiler('c') }}
    - {{ compiler('cxx') }}
  host:
    - libblas
    - libcblas
    - python
    - setuptools
    - cython
    - numpy
  run:
    - python
    - {{ pin_compatible('numpy') }}

test:
  requires:
    - pytest
    - mpmath
"""

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

js = JS()
version = Version()
# compiler = Compiler()
noarch = Noarch()
noarchr = NoarchR()
perl = Pinning(removals={"perl"})
pinning = Pinning()


class _Rebuild(NoFilter, Rebuild):
    pass


rebuild = _Rebuild(name="rebuild", cycles=[])


class _BlasRebuild(NoFilter, BlasRebuild):
    pass


blas_rebuild = _BlasRebuild(cycles=[])

matplotlib = Replacement(
    old_pkg="matplotlib",
    new_pkg="matplotlib-base",
    rationale=(
        "Unless you need `pyqt`, recipes should depend only on " "`matplotlib-base`."
    ),
    pr_limit=5,
)

G = nx.DiGraph()
G.add_node("conda", reqs=["python"])
env = builtins.__xonsh__.env  # type: ignore
env["GRAPH"] = G
env["CIRCLE_BUILD_URL"] = "hi world"


def run_test_migration(
    m, inp, output, kwargs, prb, mr_out, should_filter=False, tmpdir=None,
):
    mm_ctx = MigratorSessionContext(
        graph=G,
        smithy_version="",
        pinning_version="",
        github_username="",
        github_password="",
        circle_build_url=env["CIRCLE_BUILD_URL"],
    )
    m_ctx = MigratorContext(mm_ctx, m)
    m.bind_to_ctx(m_ctx)

    if mr_out:
        mr_out.update(bot_rerun=False)
    with open(os.path.join(tmpdir, "meta.yaml"), "w") as f:
        f.write(inp)

    # read the conda-forge.yml
    if os.path.exists(os.path.join(tmpdir, "..", "conda-forge.yml")):
        with open(os.path.join(tmpdir, "..", "conda-forge.yml"), "r") as fp:
            cf_yml = fp.read()
    else:
        cf_yml = "{}"

    # Load the meta.yaml (this is done in the graph)
    try:
        name = parse_meta_yaml(inp)["package"]["name"]
    except Exception:
        name = "blah"

    pmy = populate_feedstock_attributes(name, inp, cf_yml)

    # these are here for legacy migrators
    pmy["version"] = pmy["meta_yaml"]["package"]["version"]
    pmy["req"] = set()
    for k in ["build", "host", "run"]:
        req = pmy["meta_yaml"].get("requirements", {}) or {}
        _set = req.get(k) or set()
        pmy["req"] |= set(_set)
    pmy["raw_meta_yaml"] = inp
    pmy.update(kwargs)

    assert m.filter(pmy) is should_filter
    if should_filter:
        return pmy

    m.run_pre_piggyback_migrations(
        tmpdir, pmy, hash_type=pmy.get("hash_type", "sha256"),
    )
    mr = m.migrate(tmpdir, pmy, hash_type=pmy.get("hash_type", "sha256"))
    m.run_post_piggyback_migrations(
        tmpdir, pmy, hash_type=pmy.get("hash_type", "sha256"),
    )

    assert mr_out == mr
    if not mr:
        return pmy

    pmy.update(PRed=[frozen_to_json_friendly(mr)])
    with open(os.path.join(tmpdir, "meta.yaml"), "r") as f:
        actual_output = f.read()
    # strip jinja comments
    pat = re.compile(r"{#.*#}")
    actual_output = pat.sub("", actual_output)
    output = pat.sub("", output)
    assert actual_output == output
    if isinstance(m, Compiler):
        assert m.messages in m.pr_body(None)
    # TODO: fix subgraph here (need this to be xsh file)
    elif isinstance(m, Version):
        pass
    elif isinstance(m, Rebuild):
        return pmy
    else:
        assert prb in m.pr_body(None)
    assert m.filter(pmy) is True

    return pmy


@pytest.mark.skip
def test_js_migrator(tmpdir):
    run_test_migration(
        m=js,
        inp=sample_js,
        output=correct_js,
        kwargs={},
        prb="Please merge the PR only after the tests have passed.",
        mr_out={"migrator_name": "JS", "migrator_version": JS.migrator_version},
        tmpdir=tmpdir,
    )


@pytest.mark.skip
def test_js_migrator2(tmpdir):
    run_test_migration(
        m=js,
        inp=sample_js2,
        output=correct_js2,  # noqa
        kwargs={},
        prb="Please merge the PR only after the tests have passed.",
        mr_out={"migrator_name": "JS", "migrator_version": JS.migrator_version},
        tmpdir=tmpdir,
    )


@pytest.mark.skip
def test_cb3(tmpdir):
    run_test_migration(
        m=compiler,
        inp=sample_cb3,
        output=correct_cb3,
        kwargs={},
        prb="N/A",
        mr_out={
            "migrator_name": "Compiler",
            "migrator_version": Compiler.migrator_version,
        },
        tmpdir=tmpdir,
    )


def test_noarch(tmpdir):
    # It seems this injects some bad state somewhere, mostly because it isn't
    # valid yaml
    run_test_migration(
        m=noarch,
        inp=sample_noarch,
        output=updated_noarch,
        kwargs={
            "feedstock_name": "xpdan",
            "req": [
                "python",
                "pip",
                "numpy",
                "scipy",
                "matplotlib",
                "pyyaml",
                "scikit-beam",
                "pyfai",
                "pyxdameraulevenshtein",
                "xray-vision",
                "databroker",
                "bluesky",
                "streamz_ext",
                "xpdsim",
                "shed",
                "xpdview",
                "ophyd",
                "xpdconf",
            ],
        },
        prb="I think this feedstock could be built with noarch.\n"
        "This means that the package only needs to be built "
        "once, drastically reducing CI usage.\n",
        mr_out={"migrator_name": "Noarch", "migrator_version": Noarch.migrator_version},
        tmpdir=tmpdir,
    )


def test_noarch_space(tmpdir):
    # It seems this injects some bad state somewhere, mostly because it isn't
    # valid yaml
    run_test_migration(
        m=noarch,
        inp=sample_noarch_space,
        output=updated_noarch_space,
        kwargs={
            "feedstock_name": "xpdan",
            "req": [
                "python",
                "pip",
                "numpy",
                "scipy",
                "matplotlib",
                "pyyaml",
                "scikit-beam",
                "pyfai",
                "pyxdameraulevenshtein",
                "xray-vision",
                "databroker",
                "bluesky",
                "streamz_ext",
                "xpdsim",
                "shed",
                "xpdview",
                "ophyd",
                "xpdconf",
            ],
        },
        prb="I think this feedstock could be built with noarch.\n"
        "This means that the package only needs to be built "
        "once, drastically reducing CI usage.\n",
        mr_out={"migrator_name": "Noarch", "migrator_version": Noarch.migrator_version},
        tmpdir=tmpdir,
    )


def test_noarch_space_python(tmpdir):
    run_test_migration(
        m=noarch,
        inp=sample_noarch_space,
        output=updated_noarch_space,
        kwargs={"feedstock_name": "python"},
        prb="I think this feedstock could be built with noarch.\n"
        "This means that the package only needs to be built "
        "once, drastically reducing CI usage.\n",
        mr_out={"migrator_name": "Noarch", "migrator_version": Noarch.migrator_version},
        should_filter=True,
        tmpdir=tmpdir,
    )


def test_perl(tmpdir):
    run_test_migration(
        m=perl,
        inp=sample_pinning,
        output=updated_perl,
        kwargs={"req": {"toolchain3", "perl", "expat"}},
        prb="I noticed that this recipe has version pinnings that may not be needed.",
        mr_out={
            "migrator_name": "Pinning",
            "migrator_version": Pinning.migrator_version,
        },
        tmpdir=tmpdir,
    )


def test_perl_pinning(tmpdir):
    run_test_migration(
        m=pinning,
        inp=sample_pinning,
        output=updated_pinning,
        kwargs={"req": {"toolchain3", "perl", "expat"}},
        prb="perl: 5.22.2.1",
        mr_out={
            "migrator_name": "Pinning",
            "migrator_version": Pinning.migrator_version,
        },
        tmpdir=tmpdir,
    )


def test_nnoarch_r(tmpdir):
    run_test_migration(
        m=noarchr,
        inp=sample_r_base,
        output=updated_r_base,
        kwargs={"feedstock_name": "r-stabledist"},
        prb="I think this feedstock could be built with noarch",
        mr_out={
            "migrator_name": "NoarchR",
            "migrator_version": noarchr.migrator_version,
        },
        tmpdir=tmpdir,
    )


def test_rebuild_r(tmpdir):
    run_test_migration(
        m=rebuild,
        inp=sample_r_base2,
        output=updated_r_base2,
        kwargs={"feedstock_name": "r-stabledist"},
        prb="It is likely this feedstock needs to be rebuilt.",
        mr_out={
            "migrator_name": "_Rebuild",
            "migrator_version": rebuild.migrator_version,
            "name": "rebuild",
        },
        tmpdir=tmpdir,
    )


def test_nnoarch_r_licenses(tmpdir):
    run_test_migration(
        m=noarchr,
        inp=sample_r_licenses_noarch,
        output=updated_r_licenses_noarch,
        kwargs={"feedstock_name": "r-stabledist"},
        prb="I think this feedstock could be built with noarch",
        mr_out={
            "migrator_name": "NoarchR",
            "migrator_version": noarchr.migrator_version,
        },
        tmpdir=tmpdir,
    )


def test_blas_rebuild(tmpdir):
    run_test_migration(
        m=blas_rebuild,
        inp=sample_blas,
        output=updated_blas,
        kwargs={"feedstock_name": "scipy"},
        prb="This PR has been triggered in an effort to update for new BLAS scheme.",
        mr_out={
            "migrator_name": "_BlasRebuild",
            "migrator_version": blas_rebuild.migrator_version,
            "name": "blas2",
        },
        tmpdir=tmpdir,
    )


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
