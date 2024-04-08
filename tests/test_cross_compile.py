import os

from flaky import flaky
from test_migrators import run_test_migration

from conda_forge_tick.migrators import (
    Build2HostMigrator,
    CrossPythonMigrator,
    CrossRBaseMigrator,
    GuardTestingMigrator,
    NoCondaInspectMigrator,
    UpdateCMakeArgsMigrator,
    UpdateConfigSubGuessMigrator,
    Version,
)

config_migrator = UpdateConfigSubGuessMigrator()
guard_testing_migrator = GuardTestingMigrator()
cmake_migrator = UpdateCMakeArgsMigrator()
cross_python_migrator = CrossPythonMigrator()
cross_rbase_migrator = CrossRBaseMigrator()
b2h_migrator = Build2HostMigrator()
nci_migrator = NoCondaInspectMigrator()

version_migrator_autoconf = Version(
    set(),
    piggy_back_migrations=[config_migrator, cmake_migrator, guard_testing_migrator],
)
version_migrator_cmake = Version(
    set(),
    piggy_back_migrations=[
        cmake_migrator,
        guard_testing_migrator,
        cross_rbase_migrator,
        cross_python_migrator,
    ],
)
version_migrator_python = Version(
    set(),
    piggy_back_migrations=[cross_python_migrator],
)
version_migrator_rbase = Version(
    set(),
    piggy_back_migrations=[cross_rbase_migrator],
)
version_migrator_b2h = Version(
    set(),
    piggy_back_migrations=[b2h_migrator],
)
version_migrator_nci = Version(
    set(),
    piggy_back_migrations=[nci_migrator],
)

config_recipe = """\
{% set version = "7.0" %}

package:
  name: readline
  version: {{ version }}

source:
  url: https://ftp.gnu.org/gnu/readline/readline-{{ version }}.tar.gz
  sha256: 750d437185286f40a369e1e4f4764eda932b9459b5ec9a731628393dd3d32334

build:
  skip: true  # [win]
  number: 2
  run_exports:
    # change soname at major ver: https://abi-laboratory.pro/tracker/timeline/readline/
    - {{ pin_subpackage('readline') }}

requirements:
  build:
    - pkg-config
    - {{ compiler('c') }}
    - make
    - cmake
  host:
    - ncurses
  run:
    - ncurses

about:
  home: https://cnswww.cns.cwru.edu/php/chet/readline/rltop.html
  license: GPL-3.0-only
  license_file: COPYING
  summary: library for editing command lines as they are typed in

extra:
  recipe-maintainers:
    - croth1
"""

config_recipe_correct = """\
{% set version = "8.0" %}

package:
  name: readline
  version: {{ version }}

source:
  url: https://ftp.gnu.org/gnu/readline/readline-{{ version }}.tar.gz
  sha256: e339f51971478d369f8a053a330a190781acb9864cf4c541060f12078948e461

build:
  skip: true  # [win]
  number: 0
  run_exports:
    # change soname at major ver: https://abi-laboratory.pro/tracker/timeline/readline/
    - {{ pin_subpackage('readline') }}

requirements:
  build:
    - pkg-config
    - gnuconfig  # [unix]
    - {{ compiler('c') }}
    - make
    - cmake
  host:
    - ncurses
  run:
    - ncurses

about:
  home: https://cnswww.cns.cwru.edu/php/chet/readline/rltop.html
  license: GPL-3.0-only
  license_file: COPYING
  summary: library for editing command lines as they are typed in

extra:
  recipe-maintainers:
    - croth1
"""


config_recipe_correct_make_check = """\
{% set version = "8.0" %}

package:
  name: readline
  version: {{ version }}

source:
  url: https://ftp.gnu.org/gnu/readline/readline-{{ version }}.tar.gz
  sha256: e339f51971478d369f8a053a330a190781acb9864cf4c541060f12078948e461

build:
  skip: true  # [win]
  number: 0
  run_exports:
    # change soname at major ver: https://abi-laboratory.pro/tracker/timeline/readline/
    - {{ pin_subpackage('readline') }}

requirements:
  build:
    - pkg-config
    - gnuconfig  # [unix]
    - {{ compiler('c') }}
    - make
    - cmake
  host:
    - ncurses
  run:
    - ncurses

about:
  home: https://cnswww.cns.cwru.edu/php/chet/readline/rltop.html
  license: GPL-3.0-only
  license_file: COPYING
  summary: library for editing command lines as they are typed in

extra:
  recipe-maintainers:
    - croth1
"""


config_recipe_correct_cmake = """\
{% set version = "8.0" %}

package:
  name: readline
  version: {{ version }}

source:
  url: https://ftp.gnu.org/gnu/readline/readline-{{ version }}.tar.gz
  sha256: e339f51971478d369f8a053a330a190781acb9864cf4c541060f12078948e461

build:
  skip: true  # [win]
  number: 0
  run_exports:
    # change soname at major ver: https://abi-laboratory.pro/tracker/timeline/readline/
    - {{ pin_subpackage('readline') }}

requirements:
  build:
    - pkg-config
    - {{ compiler('c') }}
    - make
    - cmake
  host:
    - ncurses
  run:
    - ncurses

about:
  home: https://cnswww.cns.cwru.edu/php/chet/readline/rltop.html
  license: GPL-3.0-only
  license_file: COPYING
  summary: library for editing command lines as they are typed in

extra:
  recipe-maintainers:
    - croth1
"""

rbase_recipe = """\
{% set version = "2.0.0" %}
{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-magrittr
  version: {{ version|replace("-", "_") }}

source:
  url:
    - {{ cran_mirror }}/src/contrib/magrittr_{{ version }}.tar.gz
    - {{ cran_mirror }}/src/contrib/Archive/magrittr/magrittr_{{ version }}.tar.gz
  sha256: 05c45943ada9443134caa0ab24db4a962b629f00b755ccf039a2a2a7b2c92ae8

build:
  merge_build_host: true  # [win]
  number: 1
  rpaths:
    - lib/R/lib/
    - lib/

requirements:
  build:
    - {{ compiler('c') }}              # [not win]
    - {{ compiler('m2w64_c') }}        # [win]
    - {{ posix }}filesystem        # [win]
    - {{ posix }}make
    - {{ posix }}sed               # [win]
    - {{ posix }}coreutils         # [win]
    - {{ posix }}zip               # [win]
  host:
    - r-base
    - r-rlang
  run:
    - r-base
    - r-rlang
    - {{ native }}gcc-libs         # [win]

test:
  commands:
    - $R -e "library('magrittr')"           # [not win]
    - "\\"%R%\\" -e \\"library('magrittr')\\""  # [win]

about:
  home: https://magrittr.tidyverse.org, https://github.com/tidyverse/magrittr
  license: MIT
  summary: Provides a mechanism for chaining commands with a new forward-pipe operator, %>%. This operator will forward a value, or the result of an expression, into the next function call/expression. There is flexible support for the type of right-hand side expressions. For more information, see package vignette. To quote
    Rene Magritte, "Ceci n'est pas un pipe."
  license_family: MIT
  license_file:
    - {{ environ["PREFIX"] }}/lib/R/share/licenses/MIT
    - LICENSE

extra:
  recipe-maintainers:
    - conda-forge/r
    - ocefpaf
"""  # noqa

rbase_recipe_correct = """\
{% set version = "2.0.1" %}
{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-magrittr
  version: {{ version|replace("-", "_") }}

source:
  url:
    - {{ cran_mirror }}/src/contrib/magrittr_{{ version }}.tar.gz
    - {{ cran_mirror }}/src/contrib/Archive/magrittr/magrittr_{{ version }}.tar.gz
  sha256: 75c265d51cc2b34beb27040edb09823c7b954d3990a7a931e40690b75d4aad5f

build:
  merge_build_host: true  # [win]
  number: 0
  rpaths:
    - lib/R/lib/
    - lib/

requirements:
  build:
    - cross-r-base {{ r_base }}  # [build_platform != target_platform]
    - r-rlang                    # [build_platform != target_platform]
    - {{ compiler('c') }}              # [not win]
    - {{ compiler('m2w64_c') }}        # [win]
    - {{ posix }}filesystem        # [win]
    - {{ posix }}make
    - {{ posix }}sed               # [win]
    - {{ posix }}coreutils         # [win]
    - {{ posix }}zip               # [win]
  host:
    - r-base
    - r-rlang
  run:
    - r-base
    - r-rlang
    - {{ native }}gcc-libs         # [win]

test:
  commands:
    - $R -e "library('magrittr')"           # [not win]
    - "\\"%R%\\" -e \\"library('magrittr')\\""  # [win]

about:
  home: https://magrittr.tidyverse.org, https://github.com/tidyverse/magrittr
  license: MIT
  summary: Provides a mechanism for chaining commands with a new forward-pipe operator, %>%. This operator will forward a value, or the result of an expression, into the next function call/expression. There is flexible support for the type of right-hand side expressions. For more information, see package vignette. To quote
    Rene Magritte, "Ceci n'est pas un pipe."
  license_family: MIT
  license_file:
    - {{ environ["PREFIX"] }}/lib/R/share/licenses/MIT
    - LICENSE

extra:
  recipe-maintainers:
    - conda-forge/r
    - ocefpaf
"""  # noqa


python_recipe = """\
{% set version = "1.19.0" %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 153cf8b0176e57a611931981acfe093d2f7fef623b48f91176efa199798a6b90

build:
  number: 0
  skip: true  # [py27]
  entry_points:
    - f2py = numpy.f2py.f2py2e:main  # [win]

requirements:
  build:
    - {{ compiler('c') }}
    # gcc 7.3 segfaults on aarch64
    - clangdev    # [aarch64]
  host:
    - python
    - pip
    - cython
    - libblas
    - libcblas
    - liblapack
  run:
    - python

test:
  requires:
    - pytest
    - hypothesis
  commands:
    - f2py -h
    - export OPENBLAS_NUM_THREADS=1  # [unix]
    - set OPENBLAS_NUM_THREADS=1  # [win]
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Array processing for numbers, strings, records, and objects.
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

python_recipe_correct = """\
{% set version = "1.19.1" %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 1396e6c3d20cbfc119195303b0272e749610b7042cc498be4134f013e9a3215c

build:
  number: 0
  skip: true  # [py27]
  entry_points:
    - f2py = numpy.f2py.f2py2e:main  # [win]

requirements:
  build:
    - python                                 # [build_platform != target_platform]
    - cross-python_{{ target_platform }}     # [build_platform != target_platform]
    - cython                                 # [build_platform != target_platform]
    - {{ compiler('c') }}
    # gcc 7.3 segfaults on aarch64
    - clangdev    # [aarch64]
  host:
    - python
    - pip
    - cython
    - libblas
    - libcblas
    - liblapack
  run:
    - python

test:
  requires:
    - pytest
    - hypothesis
  commands:
    - f2py -h
    - export OPENBLAS_NUM_THREADS=1  # [unix]
    - set OPENBLAS_NUM_THREADS=1  # [win]
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Array processing for numbers, strings, records, and objects.
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

python_no_build_recipe = """\
{% set version = "2020.4.5.2" %}

{% set pip_version = "19.1.1" %}
{% set setuptools_version = "41.0.1" %}

package:
  name: certifi
  version: {{ version }}

source:
  - url: https://pypi.io/packages/source/c/certifi/certifi-{{ version }}.tar.gz
    sha256: 5ad7e9a056d25ffa5082862e36f119f7f7cec6457fa07ee2f8c339814b80c9b1
    folder: certifi
  # bootstrap pip and setuptools to avoid circular dependency
  # but without losing metadata
  - url: https://pypi.io/packages/py2.py3/p/pip/pip-{{ pip_version }}-py2.py3-none-any.whl
    sha256: 993134f0475471b91452ca029d4390dc8f298ac63a712814f101cd1b6db46676
    folder: pip_wheel
  - url: https://pypi.io/packages/py2.py3/s/setuptools/setuptools-{{ setuptools_version }}-py2.py3-none-any.whl
    sha256: c7769ce668c7a333d84e17fe8b524b1c45e7ee9f7908ad0a73e1eda7e6a5aebf
    folder: setuptools_wheel

build:
  number: 0

requirements:
  host:
    - python
  run:
    - python

test:
  imports:
    - certifi

about:
  home: http://certifi.io/
  license: ISC
  license_file: certifi/LICENSE
  summary: Python package for providing Mozilla's CA Bundle.
  description: |
    Certifi is a curated collection of Root Certificates for validating the
    trustworthiness of SSL certificates while verifying the identity of TLS
    hosts.
  doc_url: https://pypi.python.org/pypi/certifi
  dev_url: https://github.com/certifi/python-certifi
  doc_source_url: https://github.com/certifi/certifi.io/blob/master/README.rst

extra:
  recipe-maintainers:
    - jakirkham
    - pelson
    - sigmavirus24
    - ocefpaf
    - mingwandroid
    - jjhelmus
"""  # noqa

python_no_build_recipe_correct = """\
{% set version = "2020.6.20" %}

{% set pip_version = "19.1.1" %}
{% set setuptools_version = "41.0.1" %}

package:
  name: certifi
  version: {{ version }}

source:
  - url: https://pypi.io/packages/source/c/certifi/certifi-{{ version }}.tar.gz
    sha256: 5930595817496dd21bb8dc35dad090f1c2cd0adfaf21204bf6732ca5d8ee34d3
    folder: certifi
  # bootstrap pip and setuptools to avoid circular dependency
  # but without losing metadata
  - url: https://pypi.io/packages/py2.py3/p/pip/pip-{{ pip_version }}-py2.py3-none-any.whl
    sha256: 993134f0475471b91452ca029d4390dc8f298ac63a712814f101cd1b6db46676
    folder: pip_wheel
  - url: https://pypi.io/packages/py2.py3/s/setuptools/setuptools-{{ setuptools_version }}-py2.py3-none-any.whl
    sha256: c7769ce668c7a333d84e17fe8b524b1c45e7ee9f7908ad0a73e1eda7e6a5aebf
    folder: setuptools_wheel

build:
  number: 0

requirements:
  build:
    - python                                 # [build_platform != target_platform]
    - cross-python_{{ target_platform }}     # [build_platform != target_platform]
  host:
    - python
  run:
    - python

test:
  imports:
    - certifi

about:
  home: http://certifi.io/
  license: ISC
  license_file: certifi/LICENSE
  summary: Python package for providing Mozilla's CA Bundle.
  description: |
    Certifi is a curated collection of Root Certificates for validating the
    trustworthiness of SSL certificates while verifying the identity of TLS
    hosts.
  doc_url: https://pypi.python.org/pypi/certifi
  dev_url: https://github.com/certifi/python-certifi
  doc_source_url: https://github.com/certifi/certifi.io/blob/master/README.rst

extra:
  recipe-maintainers:
    - jakirkham
    - pelson
    - sigmavirus24
    - ocefpaf
    - mingwandroid
    - jjhelmus
"""  # noqa


python_recipe_b2h = """\
{% set version = "1.19.0" %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 153cf8b0176e57a611931981acfe093d2f7fef623b48f91176efa199798a6b90

build:
  number: 0
  skip: true  # [py27]
  entry_points:
    - f2py = numpy.f2py.f2py2e:main  # [win]

requirements:
  build:
    - python
    - pip
    - cython
    - libblas
    - libcblas
    - liblapack
  run:
    - python

test:
  requires:
    - pytest
    - hypothesis
  commands:
    - f2py -h
    - export OPENBLAS_NUM_THREADS=1  # [unix]
    - set OPENBLAS_NUM_THREADS=1  # [win]
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Array processing for numbers, strings, records, and objects.
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

python_recipe_b2h_correct = """\
{% set version = "1.19.1" %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 1396e6c3d20cbfc119195303b0272e749610b7042cc498be4134f013e9a3215c

build:
  number: 0
  skip: true  # [py27]
  entry_points:
    - f2py = numpy.f2py.f2py2e:main  # [win]

requirements:
  host:
    - python
    - pip
    - cython
    - libblas
    - libcblas
    - liblapack
  run:
    - python

test:
  requires:
    - pytest
    - hypothesis
  commands:
    - f2py -h
    - export OPENBLAS_NUM_THREADS=1  # [unix]
    - set OPENBLAS_NUM_THREADS=1  # [win]
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Array processing for numbers, strings, records, and objects.
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


python_recipe_b2h_buildok = """\
{% set version = "1.19.0" %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 153cf8b0176e57a611931981acfe093d2f7fef623b48f91176efa199798a6b90

build:
  number: 0
  skip: true  # [py27]
  entry_points:
    - f2py = numpy.f2py.f2py2e:main  # [win]

requirements:
  build:
    - {{ compiler('c') }}
    - python
    - pip
    - cython
    - libblas
    - libcblas
    - liblapack
  run:
    - python

test:
  requires:
    - pytest
    - hypothesis
  commands:
    - f2py -h
    - export OPENBLAS_NUM_THREADS=1  # [unix]
    - set OPENBLAS_NUM_THREADS=1  # [win]
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Array processing for numbers, strings, records, and objects.
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

python_recipe_b2h_buildok_correct = """\
{% set version = "1.19.1" %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 1396e6c3d20cbfc119195303b0272e749610b7042cc498be4134f013e9a3215c

build:
  number: 0
  skip: true  # [py27]
  entry_points:
    - f2py = numpy.f2py.f2py2e:main  # [win]

requirements:
  build:
    - {{ compiler('c') }}
    - python
    - pip
    - cython
    - libblas
    - libcblas
    - liblapack
  run:
    - python

test:
  requires:
    - pytest
    - hypothesis
  commands:
    - f2py -h
    - export OPENBLAS_NUM_THREADS=1  # [unix]
    - set OPENBLAS_NUM_THREADS=1  # [win]
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Array processing for numbers, strings, records, and objects.
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


python_recipe_b2h_bhskip = """\
{% set version = "1.19.0" %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 153cf8b0176e57a611931981acfe093d2f7fef623b48f91176efa199798a6b90

build:
  number: 0
  skip: true  # [py27]
  entry_points:
    - f2py = numpy.f2py.f2py2e:main  # [win]

requirements:
  build:
    - {{ compiler('c') }}
  host:
  run:
    - python

test:
  requires:
    - pytest
    - hypothesis
  commands:
    - f2py -h
    - export OPENBLAS_NUM_THREADS=1  # [unix]
    - set OPENBLAS_NUM_THREADS=1  # [win]
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Array processing for numbers, strings, records, and objects.
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

python_recipe_b2h_bhskip_correct = """\
{% set version = "1.19.1" %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 1396e6c3d20cbfc119195303b0272e749610b7042cc498be4134f013e9a3215c

build:
  number: 0
  skip: true  # [py27]
  entry_points:
    - f2py = numpy.f2py.f2py2e:main  # [win]

requirements:
  build:
    - {{ compiler('c') }}
  host:
  run:
    - python

test:
  requires:
    - pytest
    - hypothesis
  commands:
    - f2py -h
    - export OPENBLAS_NUM_THREADS=1  # [unix]
    - set OPENBLAS_NUM_THREADS=1  # [win]
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Array processing for numbers, strings, records, and objects.
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


python_recipe_nci = """\
{% set version = "1.19.0" %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 153cf8b0176e57a611931981acfe093d2f7fef623b48f91176efa199798a6b90

build:
  number: 0
  skip: true  # [py27]
  entry_points:
    - f2py = numpy.f2py.f2py2e:main  # [win]

requirements:
  host:
    - python
    - pip
    - cython
    - libblas
    - libcblas
    - liblapack
  run:
    - python

test:
  requires:
    - pytest
    - hypothesis
  commands:
    - f2py -h
    - export OPENBLAS_NUM_THREADS=1  # [unix]
    - set OPENBLAS_NUM_THREADS=1  # [win]
    - conda inspect linkages  # comment
    - conda inspect objects  # comment
    - conda inspect cars  # comment
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Array processing for numbers, strings, records, and objects.
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

python_recipe_nci_correct = """\
{% set version = "1.19.1" %}

package:
  name: numpy
  version: {{ version }}

source:
  url: https://github.com/numpy/numpy/releases/download/v{{ version }}/numpy-{{ version }}.tar.gz
  sha256: 1396e6c3d20cbfc119195303b0272e749610b7042cc498be4134f013e9a3215c

build:
  number: 0
  skip: true  # [py27]
  entry_points:
    - f2py = numpy.f2py.f2py2e:main  # [win]

requirements:
  host:
    - python
    - pip
    - cython
    - libblas
    - libcblas
    - liblapack
  run:
    - python

test:
  requires:
    - pytest
    - hypothesis
  commands:
    - f2py -h
    - export OPENBLAS_NUM_THREADS=1  # [unix]
    - set OPENBLAS_NUM_THREADS=1  # [win]
  imports:
    - numpy
    - numpy.linalg.lapack_lite

about:
  home: http://numpy.scipy.org/
  license: BSD-3-Clause
  license_file: LICENSE.txt
  summary: Array processing for numbers, strings, records, and objects.
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


@flaky
def test_correct_config_sub(tmpdir):
    with open(os.path.join(tmpdir, "build.sh"), "w") as f:
        f.write("#!/bin/bash\n./configure")
    run_test_migration(
        m=version_migrator_autoconf,
        inp=config_recipe,
        output=config_recipe_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "8.0"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "8.0",
        },
        tmpdir=tmpdir,
    )
    with open(os.path.join(tmpdir, "build.sh")) as f:
        assert len(f.readlines()) == 4


@flaky
def test_make_check(tmpdir):
    with open(os.path.join(tmpdir, "build.sh"), "w") as f:
        f.write("#!/bin/bash\nmake check")
    run_test_migration(
        m=version_migrator_autoconf,
        inp=config_recipe,
        output=config_recipe_correct_make_check,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "8.0"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "8.0",
        },
        tmpdir=tmpdir,
    )
    expected = [
        "#!/bin/bash\n",
        "# Get an updated config.sub and config.guess\n",
        "cp $BUILD_PREFIX/share/gnuconfig/config.* ./support\n",
        'if [[ "${CONDA_BUILD_CROSS_COMPILATION:-}" != "1" || "${CROSSCOMPILING_EMULATOR}" != "" ]]; then\n',
        "make check\n",
        "fi\n",
    ]
    with open(os.path.join(tmpdir, "build.sh")) as f:
        lines = f.readlines()
        assert lines == expected


@flaky
def test_cmake(tmpdir):
    with open(os.path.join(tmpdir, "build.sh"), "w") as f:
        f.write("#!/bin/bash\ncmake ..\nctest")
    run_test_migration(
        m=version_migrator_cmake,
        inp=config_recipe,
        output=config_recipe_correct_cmake,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "8.0"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "8.0",
        },
        tmpdir=tmpdir,
    )
    expected = [
        "#!/bin/bash\n",
        "cmake ${CMAKE_ARGS} ..\n",
        'if [[ "${CONDA_BUILD_CROSS_COMPILATION:-}" != "1" || "${CROSSCOMPILING_EMULATOR}" != "" ]]; then\n',
        "ctest\n",
        "fi\n",
    ]
    with open(os.path.join(tmpdir, "build.sh")) as f:
        lines = f.readlines()
        assert lines == expected


@flaky
def test_cross_rbase(tmpdir):
    run_test_migration(
        m=version_migrator_rbase,
        inp=rbase_recipe,
        output=rbase_recipe_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "2.0.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "2.0.1",
        },
        tmpdir=tmpdir,
    )


@flaky
def test_cross_rbase_build_sh(tmpdir):
    with open(os.path.join(tmpdir, "build.sh"), "w") as f:
        f.write("#!/bin/bash\nR CMD INSTALL --build .")
    run_test_migration(
        m=version_migrator_rbase,
        inp=rbase_recipe,
        output=rbase_recipe_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "2.0.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "2.0.1",
        },
        tmpdir=tmpdir,
    )
    expected = [
        "#!/bin/bash\n",
        "\n",
        "export DISABLE_AUTOBREW=1\n",
        "\n",
        "# shellcheck disable=SC2086\n",
        "${R} CMD INSTALL --build . ${R_ARGS}\n",
    ]
    with open(os.path.join(tmpdir, "build.sh")) as f:
        lines = f.readlines()
        assert lines == expected


@flaky
def test_cross_python(tmpdir):
    run_test_migration(
        m=version_migrator_python,
        inp=python_recipe,
        output=python_recipe_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmpdir=tmpdir,
    )


@flaky
def test_cross_python_no_build(tmpdir):
    run_test_migration(
        m=version_migrator_python,
        inp=python_no_build_recipe,
        output=python_no_build_recipe_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "2020.6.20"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "2020.6.20",
        },
        tmpdir=tmpdir,
    )


@flaky
def test_build2host(tmpdir):
    run_test_migration(
        m=version_migrator_b2h,
        inp=python_recipe_b2h,
        output=python_recipe_b2h_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmpdir=tmpdir,
    )


@flaky
def test_build2host_buildok(tmpdir):
    run_test_migration(
        m=version_migrator_b2h,
        inp=python_recipe_b2h_buildok,
        output=python_recipe_b2h_buildok_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmpdir=tmpdir,
    )


@flaky
def test_build2host_bhskip(tmpdir):
    run_test_migration(
        m=version_migrator_b2h,
        inp=python_recipe_b2h_bhskip,
        output=python_recipe_b2h_bhskip_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmpdir=tmpdir,
    )


@flaky
def test_nocondainspect(tmpdir):
    run_test_migration(
        m=version_migrator_nci,
        inp=python_recipe_nci,
        output=python_recipe_nci_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmpdir=tmpdir,
    )
