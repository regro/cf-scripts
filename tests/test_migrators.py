import os

import pytest

from conda_forge_tick.migrators import JS, Version, Compiler
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

sample_r = """{% set version = '1.3-1' %}

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

updated_sample_r = """{% set version = "1.3-2" %}

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

js = JS()
version = Version()
compiler = Compiler()

test_list = [
    (
        js,
        sample_js,
        correct_js,
        {},
        "Please merge the PR only after the tests have passed.",
        {"class": "JS", "class_version": JS._class_version},
    ),
    (
        version,
        one_source,
        updated_one_source,
        {"new_version": "2.4.1"},
        "Please check that the dependencies have not changed.",
        {
            "class": "Version",
            "class_version": Version._class_version,
            "version": "2.4.1",
        },
    ),
    (
        version,
        jinja_sha,
        updated_jinja_sha,
        {"new_version": "2.4.1"},
        "Please check that the dependencies have not changed.",
        {
            "class": "Version",
            "class_version": Version._class_version,
            "version": "2.4.1",
        },
    ),
    (
        version,
        multi_source,
        updated_multi_source,
        {"new_version": "2.4.1"},
        "Please check that the dependencies have not changed.",
        {
            "class": "Version",
            "class_version": Version._class_version,
            "version": "2.4.1",
        },
    ),
    (
        version,
        sample_r,
        updated_sample_r,
        {"new_version": "1.3_2"},
        "Please check that the dependencies have not changed.",
        {
            "class": "Version",
            "class_version": Version._class_version,
            "version": "1.3_2",
        },
    ),
    (
        version,
        cb3_multi,
        updated_cb3_multi,
        {"new_version": "6.0.0"},
        "Please check that the dependencies have not changed.",
        {
            "class": "Version",
            "class_version": Version._class_version,
            "version": "6.0.0",
        },
    ),
    (
        compiler,
        sample_cb3,
        correct_cb3,
        {},
        "N/A",
        {"class": "Compiler", "class_version": Compiler._class_version},
    ),
    # It seems this injects some bad state somewhere, mostly because it isn't
    # valid yaml
    (
        js,
        sample_js2,
        correct_js,
        {},
        "Please merge the PR only after the tests have passed.",
        {"class": "JS", "class_version": JS._class_version},
    ),
]


@pytest.mark.parametrize("m, inp, output, kwargs, prb, mr_out", test_list)
def test_migration(m, inp, output, kwargs, prb, mr_out, tmpdir):
    with open(os.path.join(tmpdir, "meta.yaml"), "w") as f:
        f.write(inp)
    # Load the meta.yaml (this is done in the graph)
    pmy = parse_meta_yaml(inp)
    if pmy:
        pmy["version"] = pmy["package"]["version"]
        pmy["req"] = set()
        for k in ["build", "host", "run"]:
            pmy["req"] |= set(pmy.get("requirements", {}).get(k, set()))
        pmy["meta_yaml"] = parse_meta_yaml(inp)
    pmy["raw_meta_yaml"] = inp
    pmy.update(kwargs)

    assert m.filter(pmy) is False

    mr = m.migrate(tmpdir, pmy)
    assert mr_out == mr

    pmy.update(PRed=[mr])
    with open(os.path.join(tmpdir, "meta.yaml"), "r") as f:
        assert f.read() == output
    if isinstance(m, Compiler):
        assert m.out in m.pr_body()
    # TODO: fix subgraph here (need this to be xsh file)
    elif isinstance(m, Version):
        pass
    else:
        assert prb in m.pr_body()
    assert m.filter(pmy) is True
