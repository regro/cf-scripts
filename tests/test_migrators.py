import os
import builtins

import pytest
import networkx as nx

from conda_forge_tick.migrators import JS, Version, Compiler, Noarch, Pinning, Rebuild
from conda_forge_tick.utils import parse_meta_yaml


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

cb3_multi = """{% set name = "pypy3.5" %}
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

updated_cb3_multi = """{% set name = "pypy3.5" %}
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

sample_cb3 = """{% set version = "1.14.5" %}
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

correct_cb3 = """{% set version = "1.14.5" %}
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

sample_noarch = """{% set name = "xpdan" %}
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


updated_noarch = """{% set name = "xpdan" %}
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

sample_noarch_space = """{% set name = "xpdan" %}
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


updated_noarch_space = """{% set name = "xpdan" %}
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


sample_pinning = """{% set version = "2.44_01" %}

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


updated_perl = """{% set version = "2.44_01" %}

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


updated_pinning = """{% set version = "2.44_01" %}

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

js = JS()
version = Version()
compiler = Compiler()
noarch = Noarch()
perl = Pinning(removals={"perl"})
pinning = Pinning()
rebuild = Rebuild(name='rebuild', cycles=[])
rebuild.filter = lambda x: False

test_list = [
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
        "Please check that the dependencies have not changed.",
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
        "Please check that the dependencies have not changed.",
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
        "Please check that the dependencies have not changed.",
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
        "Please check that the dependencies have not changed.",
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
        "Please check that the dependencies have not changed.",
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
        rebuild,
        sample_r_base,
        updated_r_base,
        {"feedstock_name": "r-stabledist"},
        "It is likely this feedstock needs to be rebuilt.",
        {"migrator_name": "Rebuild", "migrator_version": rebuild.migrator_version, "name":"rebuild"},
        False,
    ),
    (
        rebuild,
        sample_r_base2,
        updated_r_base2,
        {"feedstock_name": "r-stabledist"},
        "It is likely this feedstock needs to be rebuilt.",
        {"migrator_name": "Rebuild", "migrator_version": rebuild.migrator_version, "name":"rebuild"},
        False,
    ),
]

G = nx.DiGraph()
G.add_node("conda", reqs=["python"])
env = builtins.__xonsh_env__
env["GRAPH"] = G


@pytest.mark.parametrize(
    "m, inp, output, kwargs, prb, mr_out, should_filter", test_list
)
def test_migration(m, inp, output, kwargs, prb, mr_out, should_filter, tmpdir):
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

    pmy.update(PRed=[mr])
    with open(os.path.join(tmpdir, "meta.yaml"), "r") as f:
        assert f.read() == output
    if isinstance(m, Compiler):
        assert m.messages in m.pr_body()
    # TODO: fix subgraph here (need this to be xsh file)
    elif isinstance(m, Version):
        pass
    elif isinstance(m, Rebuild):
        return
    else:
        assert prb in m.pr_body()
    assert m.filter(pmy) is True
