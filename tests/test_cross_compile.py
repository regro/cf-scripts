import os

from conda_forge_tick.migrators import UpdateConfigSubGuessMigrator, Version

from test_migrators import run_test_migration

migrator = UpdateConfigSubGuessMigrator()

version_migrator = Version(piggy_back_migrations=[migrator])

config_recipe = """\
{% set version = "7.0" %}

package:
  name: readline
  version: {{ version }}

source:
  url: ftp://ftp.gnu.org/gnu/readline/readline-{{ version }}.tar.gz
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
  url: ftp://ftp.gnu.org/gnu/readline/readline-{{ version }}.tar.gz
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


def test_correct_config_sub(tmpdir):
    with open(os.path.join(tmpdir, "build.sh"), "w") as f:
        f.write("#!/bin/bash\n./configure")
    run_test_migration(
        m=migrator,
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
