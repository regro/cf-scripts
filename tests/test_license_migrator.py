import networkx as nx
from test_migrators import run_test_migration

from conda_forge_tick.migrators import LicenseMigrator, Version
from conda_forge_tick.migrators.license import _munge_licenses

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
LM = LicenseMigrator()
VER_LM = Version(set(), piggy_back_migrations=[LM], total_graph=TOTAL_GRAPH)

version_license = """\
{% set version = "0.8" %}

package:
  name: viscm
  version: {{ version }}

source:
  url: https://pypi.io/packages/source/v/viscm/viscm-{{ version }}.tar.gz
  sha256: dca77e463c56d42bbf915197c9b95e98913c85bef150d2e1dd18626b8c2c9c32

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

version_license_correct = """\
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

r_recipe = """\
{% set version = '0.9.0' %}
{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-fst
  version: {{ version|replace("-", "_") }}

source:
  url:
    - {{ cran_mirror }}/src/contrib/fst_{{ version }}.tar.gz
    - {{ cran_mirror }}/src/contrib/Archive/fst/fst_{{ version }}.tar.gz
  sha256: 2e8bc93b1c2c1a41f743d6338fd37a2907c907b159776e32bbc5637011a44579

build:
  merge_build_host: True  # [win]
  number: 0
  rpaths:
    - lib/R/lib/
    - lib/

requirements:
  build:
    - {{ compiler('c') }}        # [not win]
    - {{ compiler('cxx') }}      # [not win]
    - {{native}}toolchain        # [win]
    - {{posix}}filesystem        # [win]
    - {{posix}}make
    - {{posix}}sed               # [win]
    - {{posix}}coreutils         # [win]
    - {{posix}}zip               # [win]
    - llvm-openmp                # [osx]
  host:
    - r-base
    - r-rcpp
  run:
    - r-base
    - {{native}}gcc-libs         # [win]
    - r-rcpp
    - llvm-openmp                # [osx]

test:
  commands:
    - $R -e "library('fst')"           # [not win]
    - "\\"%R%\\" -e \\"library('fst')\\""  # [win]

about:
  home: https://fstpackage.github.io
  license: AGPL-3
  summary: |
    Multithreaded serialization of compressed data frames using the 'fst' format. The
    'fst' format allows for random access of stored data and compression with the LZ4
    and ZSTD compressors created by Yann Collet. The ZSTD compression library is owned
    by Facebook Inc.
  license_family: AGPL

extra:
  recipe-maintainers:
    - conda-forge/r
    - jprnz

# Package: fst
# Type: Package
# Title: Lightning Fast Serialization of Data Frames for R
# Description: Multithreaded serialization of compressed data frames using the 'fst' format. The 'fst' format allows for random access of stored data and compression with the LZ4 and ZSTD compressors created by Yann Collet. The ZSTD compression library is owned by Facebook Inc.
# Version: 0.9.0
# Date: 2019-04-02
# Authors@R: c( person("Mark", "Klik", email = "markklik@gmail.com", role = c("aut", "cre", "cph")), person("Yann", "Collet", role = c("ctb", "cph"), comment = "Yann Collet is author of the bundled LZ4 and ZSTD code and copyright holder of LZ4"), person("Facebook, Inc.", role = "cph", comment = "Bundled ZSTD code"))
# LazyData: true
# Depends: R (>= 3.0.0)
# Imports: Rcpp
# LinkingTo: Rcpp
# SystemRequirements: little-endian platform
# RoxygenNote: 6.1.1
# Suggests: testthat, bit64, data.table, lintr, nanotime, crayon
# License: AGPL-3 | file LICENSE
# Copyright: This package includes sources from the LZ4 library written by Yann Collet, sources of the ZSTD library owned by Facebook, Inc. and sources of the fstlib library owned by Mark Klik
# URL: https://fstpackage.github.io
# BugReports: https://github.com/fstpackage/fst/issues
# NeedsCompilation: yes
# Packaged: 2019-04-02 12:51:58 UTC; Mark
# Author: Mark Klik [aut, cre, cph], Yann Collet [ctb, cph] (Yann Collet is author of the bundled LZ4 and ZSTD code and copyright holder of LZ4), Facebook, Inc. [cph] (Bundled ZSTD code)
# Maintainer: Mark Klik <markklik@gmail.com>
# Repository: CRAN
# Date/Publication: 2019-04-09 04:43:13 UTC
"""  # noqa


r_recipe_correct = """\
{% set version = "0.9.2" %}
{% set posix = 'm2-' if win else '' %}
{% set native = 'm2w64-' if win else '' %}

package:
  name: r-fst
  version: {{ version|replace("-", "_") }}

source:
  url:
    - {{ cran_mirror }}/src/contrib/fst_{{ version }}.tar.gz
    - {{ cran_mirror }}/src/contrib/Archive/fst/fst_{{ version }}.tar.gz
  sha256: 23def8602af68059ae8c8ed566501518677d23cddc00beec23caec1cd12e2387

build:
  merge_build_host: true  # [win]
  number: 0
  rpaths:
    - lib/R/lib/
    - lib/

requirements:
  build:
    - {{ compiler('c') }}        # [not win]
    - {{ compiler('cxx') }}      # [not win]
    - {{native}}toolchain        # [win]
    - {{posix}}filesystem        # [win]
    - {{posix}}make
    - {{posix}}sed               # [win]
    - {{posix}}coreutils         # [win]
    - {{posix}}zip               # [win]
    - llvm-openmp                # [osx]
  host:
    - r-base
    - r-rcpp
  run:
    - r-base
    - {{native}}gcc-libs         # [win]
    - r-rcpp
    - llvm-openmp                # [osx]

test:
  commands:
    - $R -e "library('fst')"           # [not win]
    - "\\"%R%\\" -e \\"library('fst')\\""  # [win]

about:
  home: https://fstpackage.github.io
  license: AGPL-3.0-only
  summary: |
    Multithreaded serialization of compressed data frames using the 'fst' format. The
    'fst' format allows for random access of stored data and compression with the LZ4
    and ZSTD compressors created by Yann Collet. The ZSTD compression library is owned
    by Facebook Inc.
  license_family: AGPL

  license_file:
    - '{{ environ["PREFIX"] }}/lib/R/share/licenses/AGPL-3'
    - LICENSE
extra:
  recipe-maintainers:
    - conda-forge/r
    - jprnz

# Package: fst
# Type: Package
# Title: Lightning Fast Serialization of Data Frames for R
# Description: Multithreaded serialization of compressed data frames using the 'fst' format. The 'fst' format allows for random access of stored data and compression with the LZ4 and ZSTD compressors created by Yann Collet. The ZSTD compression library is owned by Facebook Inc.
# Version: 0.9.0
# Date: 2019-04-02
# Authors@R: c( person("Mark", "Klik", email = "markklik@gmail.com", role = c("aut", "cre", "cph")), person("Yann", "Collet", role = c("ctb", "cph"), comment = "Yann Collet is author of the bundled LZ4 and ZSTD code and copyright holder of LZ4"), person("Facebook, Inc.", role = "cph", comment = "Bundled ZSTD code"))
# LazyData: true
# Depends: R (>= 3.0.0)
# Imports: Rcpp
# LinkingTo: Rcpp
# SystemRequirements: little-endian platform
# RoxygenNote: 6.1.1
# Suggests: testthat, bit64, data.table, lintr, nanotime, crayon
# License: AGPL-3 | file LICENSE
# Copyright: This package includes sources from the LZ4 library written by Yann Collet, sources of the ZSTD library owned by Facebook, Inc. and sources of the fstlib library owned by Mark Klik
# URL: https://fstpackage.github.io
# BugReports: https://github.com/fstpackage/fst/issues
# NeedsCompilation: yes
# Packaged: 2019-04-02 12:51:58 UTC; Mark
# Author: Mark Klik [aut, cre, cph], Yann Collet [ctb, cph] (Yann Collet is author of the bundled LZ4 and ZSTD code and copyright holder of LZ4), Facebook, Inc. [cph] (Bundled ZSTD code)
# Maintainer: Mark Klik <markklik@gmail.com>
# Repository: CRAN
# Date/Publication: 2019-04-09 04:43:13 UTC
"""  # noqa


def test_version_license_correct(tmp_path):
    run_test_migration(
        m=VER_LM,
        inp=version_license,
        output=version_license_correct,
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmp_path=tmp_path,
    )


def test_munge_licenses():
    spdx = "".join(
        _munge_licenses(
            [
                "MIT + file LICENSE | GPL (>= 2) + file LICENSE | file LICENSE + file BLAH",
            ],
        ),
    )
    assert spdx == "MIT OR GPL-2.0-or-later"


def test_version_license_correct_r(tmp_path):
    run_test_migration(
        m=VER_LM,
        inp=r_recipe,
        output=r_recipe_correct,
        kwargs={"new_version": "0.9.2"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.9.2",
        },
        tmp_path=tmp_path,
    )
