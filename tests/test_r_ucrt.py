import networkx as nx
from test_migrators import run_test_migration

from conda_forge_tick.migrators import RUCRTCleanup, Version

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
r_ucrt_migrator = RUCRTCleanup()
version_migrator_rbase = Version(
    set(),
    piggy_back_migrations=[r_ucrt_migrator],
    total_graph=TOTAL_GRAPH,
)

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
  skip: True   # [win]
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
    - {{native}}gmp
    - {{ native }}mpfr
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
  summary: |
    Provides a mechanism for chaining commands with a new forward-pipe operator, %>%. This operator will forward a
    value, or the result of an expression, into the next function call/expression. There is flexible support for the
    type of right-hand side expressions. For more information, see package vignette. To
    quote Rene Magritte, "Ceci n'est pas un pipe."
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

package:
  name: r-magrittr
  version: {{ version|replace("-", "_") }}

source:
  url:
    - {{ cran_mirror }}/src/contrib/magrittr_{{ version }}.tar.gz
    - {{ cran_mirror }}/src/contrib/Archive/magrittr/magrittr_{{ version }}.tar.gz
  sha256: 75c265d51cc2b34beb27040edb09823c7b954d3990a7a931e40690b75d4aad5f

build:
  # Checking windows to see if it passes. Uncomment the line if it fails.
  # skip: True   # [win]
  number: 0
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
    - gmp
    - mpfr
  run:
    - r-base
    - r-rlang

test:
  commands:
    - $R -e "library('magrittr')"           # [not win]
    - "\\"%R%\\" -e \\"library('magrittr')\\""  # [win]

about:
  home: https://magrittr.tidyverse.org, https://github.com/tidyverse/magrittr
  license: MIT
  summary: |
    Provides a mechanism for chaining commands with a new forward-pipe operator, %>%. This operator will forward a
    value, or the result of an expression, into the next function call/expression. There is flexible support for the
    type of right-hand side expressions. For more information, see package vignette. To
    quote Rene Magritte, "Ceci n'est pas un pipe."
  license_family: MIT
  license_file:
    - {{ environ["PREFIX"] }}/lib/R/share/licenses/MIT
    - LICENSE

extra:
  recipe-maintainers:
    - conda-forge/r
    - ocefpaf
"""  # noqa


def test_r_ucrt(tmp_path):
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
        tmp_path=tmp_path,
    )
