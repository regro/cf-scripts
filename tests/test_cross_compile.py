import os

from conda_forge_tick.migrators import (
    UpdateConfigSubGuessMigrator,
    Version,
    GuardTestingMigrator,
    UpdateCMakeArgsMigrator,
    CrossPythonMigrator,
)

from test_migrators import run_test_migration

config_migrator = UpdateConfigSubGuessMigrator()
guard_testing_migrator = GuardTestingMigrator()
cmake_migrator = UpdateCMakeArgsMigrator()
cross_python_migrator = CrossPythonMigrator()

version_migrator_autoconf = Version(
    set(),
    dict(),
    dict(),
    piggy_back_migrations=[config_migrator, cmake_migrator, guard_testing_migrator],
)
version_migrator_cmake = Version(
    set(),
    dict(),
    dict(),
    piggy_back_migrations=[
        cmake_migrator,
        guard_testing_migrator,
        cross_python_migrator,
    ],
)
version_migrator_python = Version(
    set(), dict(), dict(), piggy_back_migrations=[cross_python_migrator],
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
    - libtool  # [unix]
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


python_recipe = """
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
"""

python_recipe_correct = """
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
    - python         # [build_platform != target_platform]
    - cross-python   # [build_platform != target_platform]
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
"""


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
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "8.0",
        },
        tmpdir=tmpdir,
    )
    with open(os.path.join(tmpdir, "build.sh"), "r") as f:
        assert len(f.readlines()) == 4


def test_make_check(tmpdir):
    with open(os.path.join(tmpdir, "build.sh"), "w") as f:
        f.write("#!/bin/bash\nmake check")
    run_test_migration(
        m=version_migrator_autoconf,
        inp=config_recipe,
        output=config_recipe_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "8.0"},
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "8.0",
        },
        tmpdir=tmpdir,
    )
    expected = [
        "#!/bin/bash\n",
        "# Get an updated config.sub and config.guess\n",
        "cp $BUILD_PREFIX/share/libtool/build-aux/config.* ./support\n",
        'if [[ "${CONDA_BUILD_CROSS_COMPILATION}" != "1" ]]; then\n',
        "make check\n",
        "fi\n",
    ]
    with open(os.path.join(tmpdir, "build.sh"), "r") as f:
        lines = f.readlines()
        assert lines == expected


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
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "8.0",
        },
        tmpdir=tmpdir,
    )
    expected = [
        "#!/bin/bash\n",
        "cmake ${CMAKE_ARGS} ..\n",
        'if [[ "${CONDA_BUILD_CROSS_COMPILATION}" != "1" ]]; then\n',
        "ctest\n",
        "fi\n",
    ]
    with open(os.path.join(tmpdir, "build.sh"), "r") as f:
        lines = f.readlines()
        assert lines == expected


def test_cross_python(tmpdir):
    run_test_migration(
        m=version_migrator_python,
        inp=python_recipe,
        output=python_recipe_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmpdir=tmpdir,
    )
