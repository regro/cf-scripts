import os
import builtins
import re

import pytest
import networkx as nx

from conda_forge_tick.contexts import MigratorsContext, MigratorContext
from conda_forge_tick.migrators import (
    Version,
    LicenseMigrator,
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
    Rebuild
)

from conda_forge_tick.utils import parse_meta_yaml, frozen_to_json_friendly

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
from xonsh.lib import subprocess
from xonsh.lib.os import indir


class NoFilter:
    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        return False


class _MigrationYaml(NoFilter, MigrationYaml):
    pass


yaml_rebuild = _MigrationYaml(yaml_contents="hello world", name="hi")
yaml_rebuild.cycles = []
yaml_rebuild_no_build_number = _MigrationYaml(
    yaml_contents="hello world", name="hi", bump_number=0,
)
yaml_rebuild_no_build_number.cycles = []

yaml_test_list = [
    (
        yaml_rebuild,
        sample_yaml_rebuild,
        updated_yaml_rebuild,
        {"feedstock_name": "scipy"},
        "This PR has been triggered in an effort to update **hi**.",
        {
            "migrator_name": yaml_rebuild.__class__.__name__,
            "migrator_version": yaml_rebuild.migrator_version,
            "name": "hi",
            "bot_rerun": False,
        },
        False,
    ),
    (
        yaml_rebuild_no_build_number,
        sample_yaml_rebuild,
        updated_yaml_rebuild_no_build_number,
        {"feedstock_name": "scipy"},
        "This PR has been triggered in an effort to update **hi**.",
        {
            "migrator_name": yaml_rebuild.__class__.__name__,
            "migrator_version": yaml_rebuild.migrator_version,
            "name": "hi",
            "bot_rerun": False,
        },
        False,
    ),
]


@pytest.mark.parametrize(
    "m, inp, output, kwargs, prb, mr_out, should_filter", yaml_test_list,
)
def test_yaml_migration(m, inp, output, kwargs, prb, mr_out, should_filter, tmpdir):
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

one_source = """{% set version = "2.4.0" %}
{% set download_url = "https://github.com/git-lfs/git-lfs/releases/download" %}

package:
  name: git-lfs
  version: {{ version }}

source:
  url: {{ download_url }}/v{{ version }}/git-lfs-linux-amd64-{{ version }}.tar.gz
  fn: git-lfs-linux-amd64-{{ version }}.tar.gz
  sha256: 56728ec9219c1a9339e1e6166f551459d74d300a29b51031851759cee4d7d710

build:
  number: 0

test:
  commands:
    - git-lfs --help

about:
  home: https://git-lfs.github.com/
  license: MIT
  license_file: '{{ environ["RECIPE_DIR"] }}/LICENSE.md'
  summary: An open source Git extension for versioning large files

extra:
  recipe-maintainers:
    - dfroger
    - willirath
"""

updated_one_source = """{% set version = "2.4.1" %}
{% set download_url = "https://github.com/git-lfs/git-lfs/releases/download" %}

package:
  name: git-lfs
  version: {{ version }}

source:
  url: {{ download_url }}/v{{ version }}/git-lfs-linux-amd64-{{ version }}.tar.gz
  fn: git-lfs-linux-amd64-{{ version }}.tar.gz
  sha256: 97e2bd8b7b4dde393eef3dd37013629dadebddefcdf27649b441659bdf4bb636

build:
  number: 0

test:
  commands:
    - git-lfs --help

about:
  home: https://git-lfs.github.com/
  license: MIT
  license_file: '{{ environ["RECIPE_DIR"] }}/LICENSE.md'
  summary: An open source Git extension for versioning large files

extra:
  recipe-maintainers:
    - dfroger
    - willirath
"""

jinja_sha = """{% set version = "2.4.0" %}
{% set download_url = "https://github.com/git-lfs/git-lfs/releases/download" %}
{% set sha256 = "56728ec9219c1a9339e1e6166f551459d74d300a29b51031851759cee4d7d710" %}

package:
  name: git-lfs
  version: {{ version }}

source:
  url: {{ download_url }}/v{{ version }}/git-lfs-linux-amd64-{{ version }}.tar.gz
  fn: git-lfs-linux-amd64-{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  number: 0

test:
  commands:
    - git-lfs --help

about:
  home: https://git-lfs.github.com/
  license: MIT
  license_file: '{{ environ["RECIPE_DIR"] }}/LICENSE.md'
  summary: An open source Git extension for versioning large files

extra:
  recipe-maintainers:
    - dfroger
    - willirath
"""

updated_jinja_sha = """{% set version = "2.4.1" %}
{% set download_url = "https://github.com/git-lfs/git-lfs/releases/download" %}
{% set sha256 = "97e2bd8b7b4dde393eef3dd37013629dadebddefcdf27649b441659bdf4bb636" %}

package:
  name: git-lfs
  version: {{ version }}

source:
  url: {{ download_url }}/v{{ version }}/git-lfs-linux-amd64-{{ version }}.tar.gz
  fn: git-lfs-linux-amd64-{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  number: 0

test:
  commands:
    - git-lfs --help

about:
  home: https://git-lfs.github.com/
  license: MIT
  license_file: '{{ environ["RECIPE_DIR"] }}/LICENSE.md'
  summary: An open source Git extension for versioning large files

extra:
  recipe-maintainers:
    - dfroger
    - willirath
"""

multi_source = """{% set version = "2.4.0" %}
{% set download_url = "https://github.com/git-lfs/git-lfs/releases/download" %}

package:
  name: git-lfs
  version: {{ version }}

source:
  url: {{ download_url }}/v{{ version }}/git-lfs-linux-amd64-{{ version }}.tar.gz  # [linux]
  fn: git-lfs-linux-amd64-{{ version }}.tar.gz  # [linux]
  sha256: 56728ec9219c1a9339e1e6166f551459d74d300a29b51031851759cee4d7d710  # [linux]

  url: {{ download_url }}/v{{ version }}/git-lfs-darwin-amd64-{{ version }}.tar.gz  # [osx]
  fn: git-lfs-darwin-amd64-{{ version }}.tar.gz  # [osx]
  sha256: ab5a1391316aa9b4fd53fc6e1a2650580b543105429548bb991d6688511f2273  # [osx]

  url: {{ download_url }}/v{{ version }}/git-lfs-windows-amd64-{{ version }}.zip  # [win]
  fn: git-lfs-windows-amd64-{{ version }}.zip  # [win]
  sha256: e3dec7cd1316ef3dc5f0e99161aa2fe77aea82e1dd57a74e3ecbb1e7e459b10e  # [win]

build:
  number: 0

test:
  commands:
    - git-lfs --help

about:
  home: https://git-lfs.github.com/
  license: MIT
  license_file: '{{ environ["RECIPE_DIR"] }}/LICENSE.md'
  summary: An open source Git extension for versioning large files

extra:
  recipe-maintainers:
    - dfroger
    - willirath
"""

updated_multi_source = """{% set version = "2.4.1" %}
{% set download_url = "https://github.com/git-lfs/git-lfs/releases/download" %}

package:
  name: git-lfs
  version: {{ version }}

source:
  url: {{ download_url }}/v{{ version }}/git-lfs-linux-amd64-{{ version }}.tar.gz  # [linux]
  fn: git-lfs-linux-amd64-{{ version }}.tar.gz  # [linux]
  sha256: 97e2bd8b7b4dde393eef3dd37013629dadebddefcdf27649b441659bdf4bb636  # [linux]

  url: {{ download_url }}/v{{ version }}/git-lfs-darwin-amd64-{{ version }}.tar.gz  # [osx]
  fn: git-lfs-darwin-amd64-{{ version }}.tar.gz  # [osx]
  sha256: e41ac4988bd6bd38faf7c17562273cb57099b3650e50f66013aa36d62aa7448a  # [osx]

  url: {{ download_url }}/v{{ version }}/git-lfs-windows-amd64-{{ version }}.zip  # [win]
  fn: git-lfs-windows-amd64-{{ version }}.zip  # [win]
  sha256: ebbab07348dbe71a5c20bfbdfafe4dbbafc8deacea6e6bf4143556721c860821  # [win]

build:
  number: 0

test:
  commands:
    - git-lfs --help

about:
  home: https://git-lfs.github.com/
  license: MIT
  license_file: '{{ environ["RECIPE_DIR"] }}/LICENSE.md'
  summary: An open source Git extension for versioning large files

extra:
  recipe-maintainers:
    - dfroger
    - willirath
"""

sample_r = r"""{% set version = '1.3-1' %}

{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-rprojroot
  version: {{ version|replace("-", "_") }}

source:
  fn: rprojroot_{{ version }}.tar.gz
  url:
    - https://cran.r-project.org/src/contrib/rprojroot_{{ version }}.tar.gz
    - https://cran.r-project.org/src/contrib/Archive/rprojroot/rprojroot_{{ version }}.tar.gz
  sha256: 628c2c064b2b288264ecab6e670f9fd1d380b017a546926019fec301a5c82fca

build:
  number: 0
  skip: true  # [win32]

  rpaths:
    - lib/R/lib/
    - lib/

requirements:
  build:
    - r-base
    - r-backports

  run:
    - r-base
    - r-backports

test:
  commands:
    - $R -e "library('rprojroot')"  # [not win]
    - "\"%R%\" -e \"library('rprojroot')\""  # [win]

about:
  home: https://github.com/krlmlr/rprojroot, https://krlmlr.github.io/rprojroot
  license: GPL-3
  summary: Robust, reliable and flexible paths to files below a project root. The 'root' of a
    project is defined as a directory that matches a certain criterion, e.g., it contains
    a certain regular file.
  license_family: GPL3
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\R\share\licenses\GPL-3'  # [win]

extra:
  recipe-maintainers:
    - johanneskoester
    - bgruening
    - daler
    - jdblischak
    - cbrueffer
"""

updated_sample_r = r"""{% set version = "1.3-2" %}

{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-rprojroot
  version: {{ version|replace("-", "_") }}

source:
  fn: rprojroot_{{ version }}.tar.gz
  url:
    - https://cran.r-project.org/src/contrib/rprojroot_{{ version }}.tar.gz
    - https://cran.r-project.org/src/contrib/Archive/rprojroot/rprojroot_{{ version }}.tar.gz
  sha256: df5665834941d8b0e377a8810a04f98552201678300f168de5f58a587b73238b

build:
  number: 0
  skip: true  # [win32]

  rpaths:
    - lib/R/lib/
    - lib/

requirements:
  build:
    - r-base
    - r-backports

  run:
    - r-base
    - r-backports

test:
  commands:
    - $R -e "library('rprojroot')"  # [not win]
    - "\"%R%\" -e \"library('rprojroot')\""  # [win]

about:
  home: https://github.com/krlmlr/rprojroot, https://krlmlr.github.io/rprojroot
  license: GPL-3
  summary: Robust, reliable and flexible paths to files below a project root. The 'root' of a
    project is defined as a directory that matches a certain criterion, e.g., it contains
    a certain regular file.
  license_family: GPL3
  license_file: '{{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3'  # [unix]
  license_file: '{{ environ["PREFIX"] }}\R\share\licenses\GPL-3'  # [win]

extra:
  recipe-maintainers:
    - johanneskoester
    - bgruening
    - daler
    - jdblischak
    - cbrueffer
"""

cb3_multi = """
{# cb3_multi #}
{% set name = "pypy3.5" %}
{% set version = "5.9.0" %}

package:
  name: {{ name }}
  version: {{ version }}

source:
  - url: https://bitbucket.org/pypy/pypy/downloads/pypy3-v{{ version }}-src.tar.bz2
    fn: pypy3-v{{ version }}-src.tar.bz2
    sha256: a014f47f50a1480f871a0b82705f904b38c93c4ca069850eb37653fedafb1b97
    folder: pypy3
    patches:
      - tklib_build.patch

  - url: https://bitbucket.org/pypy/pypy/downloads/pypy2-v5.9.0-osx64.tar.bz2
    fn: pypy2-v5.9.0-osx64.tar.bz2
    sha256: 94de50ed80c7f6392ed356c03fd54cdc84858df43ad21e9e971d1b6da0f6b867
    folder: pypy2-osx

build:
  number: 0
  skip: True  # [win]
  skip_compile_pyc:
    - lib*

requirements:
  build:
    - {{ compiler('c') }}
    - python >=2.7,<3
  host:
    - python >=2.7,<3
    - libunwind  # [osx]
    - pkg-config
    - pycparser
    - openssl
    - libffi
    - sqlite
    - tk
    - zlib
    - bzip2
    - expat
    - ncurses >=6.0
    - gdbm
    - xz
    - tk
  run:
    - libunwind  # [osx]
    - openssl
    - libffi
    - sqlite
    - tk
    - zlib
    - bzip2
    - ncurses >=6.0
    - gdbm
    - xz
    - expat

test:
  commands:
    - pypy3 --help

about:
    home: http://pypy.org/
    license: MIT
    license_family: MIT
    license_file: pypy3/LICENSE
    summary: PyPy is a Python interpreter and just-in-time compiler.

extra:
  recipe-maintainers:
    - omerbenamram
    - ohadravid
"""

updated_cb3_multi = """
{# updated_cb3_multi #}
{% set name = "pypy3.5" %}
{% set version = "6.0.0" %}

package:
  name: {{ name }}
  version: {{ version }}

source:
  - url: https://bitbucket.org/pypy/pypy/downloads/pypy3-v{{ version }}-src.tar.bz2
    fn: pypy3-v{{ version }}-src.tar.bz2
    sha256: ed8005202b46d6fc6831df1d13a4613bc40084bfa42f275068edadf8954034a3
    folder: pypy3
    patches:
      - tklib_build.patch

  - url: https://bitbucket.org/pypy/pypy/downloads/pypy2-v5.9.0-osx64.tar.bz2
    fn: pypy2-v5.9.0-osx64.tar.bz2
    sha256: 94de50ed80c7f6392ed356c03fd54cdc84858df43ad21e9e971d1b6da0f6b867
    folder: pypy2-osx

build:
  number: 0
  skip: True  # [win]
  skip_compile_pyc:
    - lib*

requirements:
  build:
    - {{ compiler('c') }}
    - python >=2.7,<3
  host:
    - python >=2.7,<3
    - libunwind  # [osx]
    - pkg-config
    - pycparser
    - openssl
    - libffi
    - sqlite
    - tk
    - zlib
    - bzip2
    - expat
    - ncurses >=6.0
    - gdbm
    - xz
    - tk
  run:
    - libunwind  # [osx]
    - openssl
    - libffi
    - sqlite
    - tk
    - zlib
    - bzip2
    - ncurses >=6.0
    - gdbm
    - xz
    - expat

test:
  commands:
    - pypy3 --help

about:
    home: http://pypy.org/
    license: MIT
    license_family: MIT
    license_file: pypy3/LICENSE
    summary: PyPy is a Python interpreter and just-in-time compiler.

extra:
  recipe-maintainers:
    - omerbenamram
    - ohadravid
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
"""

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
"""

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
    - "\"%R%\" -e \"library('stabledist')\""  # [win]
"""

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
    - "\"%R%\" -e \"library('stabledist')\""  # [win]
"""


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
    - "\"%R%\" -e \"library('stabledist')\""  # [win]
"""

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
    - "\"%R%\" -e \"library('stabledist')\""  # [win]
"""

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
    - "\"%R%\" -e \"library('stabledist')\""  # [win]

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
"""

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
    - "\"%R%\" -e \"library('stabledist')\""  # [win]

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
"""

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
    - "\"%R%\" -e \"library('stabledist')\""  # [win]

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
"""

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
    - "\"%R%\" -e \"library('stabledist')\""  # [win]

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
"""

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
"""


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
"""

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
"""


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
"""


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

compress = """
{# compress #}
{% set version = "0.8" %}
package:
  name: viscm
  version: {{ version }}
source:
  url: https://pypi.io/packages/source/v/viscm/viscm-{{ version }}.zip
  sha256: 5a9677fa4751c6dd18a5a74e7ec06848e4973d0ac0af3e4d795753b15a30c759
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
  license_family: MIT
  # license_file: '' we need to an issue upstream to get a license in the source dist.
  summary: A colormap tool
extra:
  recipe-maintainers:
    - kthyng
"""

compress_correct = """
{# compress_correct #}
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
  license_family: MIT
  # license_file: '' we need to an issue upstream to get a license in the source dist.
  summary: A colormap tool
extra:
  recipe-maintainers:
    - kthyng
"""


version_license = """
{# version_license #}
{% set version = "0.8" %}

package:
  name: viscm
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/v/viscm/viscm-{{ version }}.tar.gz
  sha256: 5a9677fa4751c6dd18a5a74e7ec06848e4973d0ac0af3e4d795753b15a30c759

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
  license_family: MIT
  # license_file: '' we need to an issue upstream to get a license in the source dist.
  summary: A colormap tool

extra:
  recipe-maintainers:
    - kthyng
"""

version_license_correct = """
{# version_license_correct #}
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
lm = LicenseMigrator()
version_license_migrator = Version(piggy_back_migrations=[lm])
compiler = Compiler()
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

test_list = [
    (
        version,
        compress,
        compress_correct,
        {"new_version": "0.9"},
        "Dependencies have been updated if changed",
        {
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        False,
    ),
    (
        version_license_migrator,
        version_license,
        version_license_correct,
        {"new_version": "0.9"},
        "Dependencies have been updated if changed",
        {
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        False,
    ),
    (
        js,
        sample_js,
        correct_js,
        {},
        "Please merge the PR only after the tests have passed.",
        {"migrator_name": "JS", "migrator_version": JS.migrator_version},
        False,
    ),
    (
        version,
        one_source,
        updated_one_source,
        {"new_version": "2.4.1"},
        "Dependencies have been updated if changed",
        {
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "2.4.1",
        },
        False,
    ),
    (
        version,
        jinja_sha,
        updated_jinja_sha,
        {"new_version": "2.4.1"},
        "Dependencies have been updated if changed",
        {
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "2.4.1",
        },
        False,
    ),
    (
        version,
        multi_source,
        updated_multi_source,
        {"new_version": "2.4.1"},
        "Dependencies have been updated if changed",
        {
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "2.4.1",
        },
        False,
    ),
    (
        version,
        sample_r,
        updated_sample_r,
        {"new_version": "1.3_2"},
        "Dependencies have been updated if changed",
        {
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "1.3_2",
        },
        False,
    ),
    (
        version,
        cb3_multi,
        updated_cb3_multi,
        {"new_version": "6.0.0"},
        "Dependencies have been updated if changed",
        {
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "6.0.0",
        },
        False,
    ),
    (
        compiler,
        sample_cb3,
        correct_cb3,
        {},
        "N/A",
        {"migrator_name": "Compiler", "migrator_version": Compiler.migrator_version},
        False,
    ),
    # It seems this injects some bad state somewhere, mostly because it isn't
    # valid yaml
    (
        js,
        sample_js2,
        correct_js,
        {},
        "Please merge the PR only after the tests have passed.",
        {"migrator_name": "JS", "migrator_version": JS.migrator_version},
        False,
    ),
    (
        noarch,
        sample_noarch,
        updated_noarch,
        {
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
        "I think this feedstock could be built with noarch.\n"
        "This means that the package only needs to be built "
        "once, drastically reducing CI usage.\n",
        {"migrator_name": "Noarch", "migrator_version": Noarch.migrator_version},
        False,
    ),
    (
        noarch,
        sample_noarch_space,
        updated_noarch_space,
        {
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
        "I think this feedstock could be built with noarch.\n"
        "This means that the package only needs to be built "
        "once, drastically reducing CI usage.\n",
        {"migrator_name": "Noarch", "migrator_version": Noarch.migrator_version},
        False,
    ),
    (
        noarch,
        sample_noarch_space,
        updated_noarch_space,
        {"feedstock_name": "python"},
        "I think this feedstock could be built with noarch.\n"
        "This means that the package only needs to be built "
        "once, drastically reducing CI usage.\n",
        {"migrator_name": "Noarch", "migrator_version": Noarch.migrator_version},
        True,
    ),
    (
        perl,
        sample_pinning,
        updated_perl,
        {"req": {"toolchain3", "perl", "expat"}},
        "I noticed that this recipe has version pinnings that may not be needed.",
        {"migrator_name": "Pinning", "migrator_version": Pinning.migrator_version},
        False,
    ),
    (
        pinning,
        sample_pinning,
        updated_pinning,
        {"req": {"toolchain3", "perl", "expat"}},
        "perl: 5.22.2.1",
        {"migrator_name": "Pinning", "migrator_version": Pinning.migrator_version},
        False,
    ),
    (
        noarchr,
        sample_r_base,
        updated_r_base,
        {"feedstock_name": "r-stabledist"},
        "I think this feedstock could be built with noarch",
        {"migrator_name": "NoarchR", "migrator_version": noarchr.migrator_version},
        False,
    ),
    (
        rebuild,
        sample_r_base2,
        updated_r_base2,
        {"feedstock_name": "r-stabledist"},
        "It is likely this feedstock needs to be rebuilt.",
        {
            "migrator_name": "_Rebuild",
            "migrator_version": rebuild.migrator_version,
            "name": "rebuild",
        },
        False,
    ),
    (
        noarchr,
        sample_r_licenses_noarch,
        updated_r_licenses_noarch,
        {"feedstock_name": "r-stabledist"},
        "I think this feedstock could be built with noarch",
        {"migrator_name": "NoarchR", "migrator_version": noarchr.migrator_version},
        False,
    ),
    (
        blas_rebuild,
        sample_blas,
        updated_blas,
        {"feedstock_name": "scipy"},
        "This PR has been triggered in an effort to update for new BLAS scheme.",
        {
            "migrator_name": "_BlasRebuild",
            "migrator_version": blas_rebuild.migrator_version,
            "name": "blas2",
        },
        False,
    ),
    (
        matplotlib,
        sample_matplotlib,
        sample_matplotlib_correct,
        {},
        "I noticed that this recipe depends on `matplotlib` instead of ",
        {
            "migrator_name": "Replacement",
            "migrator_version": matplotlib.migrator_version,
        },
        False,
    ),
    # Disabled for now because the R license stuff has been purpossefully moved into the noarchR migrator
    # (
    #     noarchr,
    #     sample_r_licenses_compiled,
    #     updated_r_licenses_compiled,
    #     {"feedstock_name": "r-stabledist"},
    #     "It is likely this feedstock needs to be rebuilt.",
    #     {"migrator_name": "Rebuild", "migrator_version": rebuild.migrator_version, "name":"rebuild"},
    #     False,
    # ),
]

G = nx.DiGraph()
G.add_node("conda", reqs=["python"])
env = builtins.__xonsh__.env  # type: ignore
env["GRAPH"] = G
env["CIRCLE_BUILD_URL"] = "hi world"


@pytest.mark.parametrize(
    "m, inp, output, kwargs, prb, mr_out, should_filter", test_list,
)
def test_migration(m, inp, output, kwargs, prb, mr_out, should_filter, tmpdir):
    mm_ctx = MigratorsContext(
        graph=G,
        smithy_version="",
        pinning_version="",
        github_username="",
        github_password="",
        circle_build_url=env["CIRCLE_BUILD_URL"],
    )
    m_ctx = MigratorContext(mm_ctx, m)
    m.bind_to_ctx(m_ctx)

    mr_out.update(bot_rerun=False)
    with open(os.path.join(tmpdir, "meta.yaml"), "w") as f:
        f.write(inp)
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

    mr = m.migrate(tmpdir, pmy)
    assert mr_out == mr

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
        return
    else:
        assert prb in m.pr_body(None)
    assert m.filter(pmy) is True
