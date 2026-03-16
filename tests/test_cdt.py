import networkx as nx
from test_migrators import run_test_migration

from conda_forge_tick.migrators import CDTMigrator

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
cdt_migrator = CDTMigrator(total_graph=TOTAL_GRAPH)

freecad_recipe = """\
{% set name = "freecad" %}
{% set version = "1.0.0" %}
{% set build_number = 4 %}
{% set build_number = build_number + 500 %}  # [FEATURE_DEBUG]

package:
    name: {{ name }}
    version: {{ version }}

source:
    url: https://github.com/FreeCAD/FreeCAD/releases/download/{{ version }}/freecad_source.tar.gz
    sha256: b5af251615eeab3905b2aa5fbd432cf90c57b86f9ba2a50ca23c9cc1703f81d9
    patches:
        - patches/osx_arm64_cross_compiling.patch    # [osx and arm64]
        - patches/py313.patch

build:
    number: {{ build_number }}
    script_env:
        - USE_QT6=1

requirements:
    build:
        - python                                 # [build_platform != target_platform]
        - cross-python_{{ target_platform }}     # [build_platform != target_platform]
        - pybind11                               # [build_platform != target_platform]
        - {{ compiler("cxx") }}
        - {{ stdlib("c") }}
        - {{ cdt('mesa-libgl-devel') }}      # [linux]
        - {{ cdt('mesa-dri-drivers') }}      # [linux]
        - {{ cdt('mesa-libegl-devel') }}     # [linux]
        - {{ cdt('libselinux') }}            # [linux]
        - {{ cdt('libxdamage') }}            # [linux]
        - {{ cdt('libxfixes') }}             # [linux]
        - {{ cdt('libxxf86vm') }}            # [linux]
        - {{ cdt('libxcb') }}                # [linux]
        - {{ cdt('libxext') }}               # [linux]
        - {{ cdt('xorg-x11-server-xvfb') }}  # [linux]
        - {{ cdt('libxau') }}                # [linux]
        - {{ cdt('libxi-devel') }}           # [linux]
        - cmake
        - swig
        - ninja
        - sed                                    # [unix]
        - qt6-main                               # [build_platform != target_platform]
        - noqt5                                  # [build_platform != target_platform]
        - doxygen
    host:
        - coin3d
        - eigen
        - freetype
        - hdf5
        - libboost-devel
        - libspnav          # [linux]
        - matplotlib-base
        - noqt5
        - occt
        - pcl
        - pivy
        - ply
        - pybind11
        - pyside6
        - python
        - qt6-main
        - six
        - smesh
        - tbb-devel  # [win]
        - vtk
        - xerces-c
        - xorg-xproto   # [linux]
        - yaml-cpp
        - zlib
    run:
        - graphviz
        - gmsh
        - libspnav  # [linux]
        - numpy
        - python
        - pyside6
        - pivy
        - pyyaml
        - ply
        - six

test:
    commands:
        - freecadcmd -t 0  # [unix and build_platform == target_platform]

about:
    home: https://www.freecad.org/
    license: LGPL-2.1-or-later
    license_family: LGPL
    license_file: LICENSE
    summary: 'FreeCAD is a parametric 3D modeler made primarily to design real-life objects of any size. '
    description: |
        FreeCAD is a general purpose feature-based, parametric 3D modeler for
        CAD, MCAD, CAx, CAE and PLM, aimed directly at mechanical engineering
        and product design but also fits a wider range of uses in engineering,
        such as architecture or other engineering specialties. It is 100% Open
        Source (LGPL2+ license) and extremely modular, allowing for very
        advanced extension and customization.
        FreeCAD is based on OpenCASCADE, a powerful geometry kernel, features an
        Open Inventor-compliant 3D scene representation model provided by the
        Coin 3D library, and a broad Python API. The interface is built with Qt.
        FreeCAD runs exactly the same way on Windows, Mac OSX, BSD and Linux
        platforms.
    doc_url: https://wiki.freecad.org/Main_Page
    dev_url: https://github.com/FreeCAD/FreeCAD

extra:
    recipe-maintainers:
        - adrianinsaval
        - looooo
"""  # noqa

freecad_recipe_correct = """\
{% set name = "freecad" %}
{% set version = "1.0.0" %}
{% set build_number = 5 %}
{% set build_number = build_number + 500 %}  # [FEATURE_DEBUG]

package:
    name: {{ name }}
    version: {{ version }}

source:
    url: https://github.com/FreeCAD/FreeCAD/releases/download/{{ version }}/freecad_source.tar.gz
    sha256: b5af251615eeab3905b2aa5fbd432cf90c57b86f9ba2a50ca23c9cc1703f81d9
    patches:
        - patches/osx_arm64_cross_compiling.patch    # [osx and arm64]
        - patches/py313.patch

build:
    number: {{ build_number }}
    script_env:
        - USE_QT6=1

requirements:
    build:
        - python                                 # [build_platform != target_platform]
        - cross-python_{{ target_platform }}     # [build_platform != target_platform]
        - pybind11                               # [build_platform != target_platform]
        - {{ compiler("cxx") }}
        - {{ stdlib("c") }}
        - cmake
        - swig
        - ninja
        - sed                                    # [unix]
        - qt6-main                               # [build_platform != target_platform]
        - noqt5                                  # [build_platform != target_platform]
        - doxygen
    host:
        - coin3d
        - eigen
        - freetype
        - hdf5
        - libboost-devel
        - libspnav          # [linux]
        - matplotlib-base
        - noqt5
        - occt
        - pcl
        - pivy
        - ply
        - pybind11
        - pyside6
        - python
        - qt6-main
        - six
        - smesh
        - tbb-devel  # [win]
        - vtk
        - xerces-c
        - xorg-xproto   # [linux]
        - yaml-cpp
        - zlib
        - libgl-devel                        # [linux]
        - libegl-devel                       # [linux]
        - xorg-libxi                         # [linux]
    run:
        - graphviz
        - gmsh
        - libspnav  # [linux]
        - numpy
        - python
        - pyside6
        - pivy
        - pyyaml
        - ply
        - six

test:
    commands:
        - freecadcmd -t 0  # [unix and build_platform == target_platform]

about:
    home: https://www.freecad.org/
    license: LGPL-2.1-or-later
    license_family: LGPL
    license_file: LICENSE
    summary: 'FreeCAD is a parametric 3D modeler made primarily to design real-life objects of any size. '
    description: |
        FreeCAD is a general purpose feature-based, parametric 3D modeler for
        CAD, MCAD, CAx, CAE and PLM, aimed directly at mechanical engineering
        and product design but also fits a wider range of uses in engineering,
        such as architecture or other engineering specialties. It is 100% Open
        Source (LGPL2+ license) and extremely modular, allowing for very
        advanced extension and customization.
        FreeCAD is based on OpenCASCADE, a powerful geometry kernel, features an
        Open Inventor-compliant 3D scene representation model provided by the
        Coin 3D library, and a broad Python API. The interface is built with Qt.
        FreeCAD runs exactly the same way on Windows, Mac OSX, BSD and Linux
        platforms.
    doc_url: https://wiki.freecad.org/Main_Page
    dev_url: https://github.com/FreeCAD/FreeCAD

extra:
    recipe-maintainers:
        - adrianinsaval
        - looooo
"""  # noqa

r_rgl_recipe = """\
{% set version = "1.3.36" %}
{% set posix = 'm2-' if win else '' %}

package:
  name: r-rgl
  version: {{ version|replace("-", "_") }}

source:
  url:
    - {{ cran_mirror }}/src/contrib/rgl_{{ version }}.tar.gz
    - {{ cran_mirror }}/src/contrib/Archive/rgl/rgl_{{ version }}.tar.gz
  sha256: 15570af26b4c3c62cc66d05dced8e7d6b7c363ded97450ae4eba97c6d7491547
  patches:
    - 0001-remove-unneeded-LDFLAGS.patch

build:
  skip: true  # [ppc64le]
  number: 0
  rpaths:
    - lib/R/lib/
    - lib/

requirements:
  build:
    - cross-r-base {{ r_base }}          # [build_platform != target_platform]
    - r-htmltools                        # [build_platform != target_platform]
    - r-htmlwidgets                      # [build_platform != target_platform]
    - r-jsonlite                         # [build_platform != target_platform]
    - r-knitr                            # [build_platform != target_platform]
    - r-magrittr                         # [build_platform != target_platform]
    - {{ compiler('c') }}                # [not win]
    - {{ stdlib("c") }}                  # [not win]
    - {{ compiler('m2w64_c') }}          # [win]
    - {{ stdlib("m2w64_c") }}            # [win]
    - {{ compiler('cxx') }}              # [not win]
    - {{ compiler('m2w64_cxx') }}        # [win]
    - {{ posix }}filesystem              # [win]
    - {{ posix }}sed                     # [win]
    - {{ posix }}grep                    # [win]
    - {{ posix }}autoconf
    - {{ posix }}automake                # [not win]
    - {{ posix }}automake-wrapper        # [win]
    - pkg-config
    - {{ posix }}make
    - {{ posix }}coreutils               # [win]
    - {{ posix }}zip                     # [win]
    - {{ cdt('xorg-x11-proto-devel') }}  # [linux]
    - {{ cdt('mesa-libgl-devel') }}      # [linux]
    - {{ cdt('libx11-devel') }}          # [linux]
    - {{ cdt('libxext-devel') }}         # [linux]
    - {{ cdt('libxrender-devel') }}      # [linux]
    - {{ cdt('mesa-libgl-devel') }}      # [linux]
    - {{ cdt('mesa-libegl-devel') }}     # [linux]
    - {{ cdt('mesa-dri-drivers') }}      # [linux]
    - {{ cdt('libxau-devel') }}          # [linux]
    - {{ cdt('libdrm-devel') }}          # [linux]
    - {{ cdt('libxcomposite-devel') }}   # [linux]
    - {{ cdt('libxcursor-devel') }}      # [linux]
    - {{ cdt('libxi-devel') }}           # [linux]
    - {{ cdt('libxrandr-devel') }}       # [linux]
    - {{ cdt('libxscrnsaver-devel') }}   # [linux]
    - {{ cdt('libxtst-devel') }}         # [linux]
    - {{ cdt('libselinux-devel') }}      # [linux]
    - {{ cdt('libselinux') }}            # [linux]
    - {{ cdt('libxdamage') }}            # [linux]
    - {{ cdt('libxfixes') }}             # [linux]
    - {{ cdt('libxxf86vm') }}            # [linux]
    - {{ cdt('libxcb') }}                # [linux]
    - {{ cdt('libxext') }}               # [linux]
    - {{ cdt('expat') }}                 # [linux]
  host:
    - r-base
    - r-htmltools
    - r-htmlwidgets >=1.6.0
    - r-jsonlite >=0.9.20
    - r-knitr >=1.33
    - r-magrittr
    - expat                              # [linux]
    - freetype
    - libglu                             # [linux]
    - libpng
    - xorg-libxfixes                     # [linux]
    - zlib                               # [win]
  run:
    - r-base
    - r-htmltools
    - r-htmlwidgets >=1.6.0
    - r-jsonlite >=0.9.20
    - r-knitr >=1.33
    - r-magrittr
    - expat                              # [linux]
    - libglu                             # [linux]

test:
  commands:
    - $R -e "library('rgl')"           # [not win]

about:
  home: https://r-forge.r-project.org/projects/rgl/
  license: GPL-2.0-or-later
  summary: Provides medium to high level functions for 3D interactive graphics, including functions modelled on base graphics (plot3d(), etc.) as well as functions for constructing representations of geometric objects (cube3d(), etc.).  Output may be on screen using OpenGL, or to various standard 3D file formats
    including WebGL, PLY, OBJ, STL as well as 2D image formats, including PNG, Postscript, SVG, PGF.
  license_family: GPL
  license_file:
    - {{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2
    - {{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3

extra:
  recipe-maintainers:
    - conda-forge/r
"""  # noqa

r_rgl_recipe_correct = """\
{% set version = "1.3.36" %}
{% set posix = 'm2-' if win else '' %}

package:
  name: r-rgl
  version: {{ version|replace("-", "_") }}

source:
  url:
    - {{ cran_mirror }}/src/contrib/rgl_{{ version }}.tar.gz
    - {{ cran_mirror }}/src/contrib/Archive/rgl/rgl_{{ version }}.tar.gz
  sha256: 15570af26b4c3c62cc66d05dced8e7d6b7c363ded97450ae4eba97c6d7491547
  patches:
    - 0001-remove-unneeded-LDFLAGS.patch

build:
  skip: true  # [ppc64le]
  number: 1
  rpaths:
    - lib/R/lib/
    - lib/

requirements:
  build:
    - cross-r-base {{ r_base }}          # [build_platform != target_platform]
    - r-htmltools                        # [build_platform != target_platform]
    - r-htmlwidgets                      # [build_platform != target_platform]
    - r-jsonlite                         # [build_platform != target_platform]
    - r-knitr                            # [build_platform != target_platform]
    - r-magrittr                         # [build_platform != target_platform]
    - {{ compiler('c') }}                # [not win]
    - {{ stdlib("c") }}                  # [not win]
    - {{ compiler('m2w64_c') }}          # [win]
    - {{ stdlib("m2w64_c") }}            # [win]
    - {{ compiler('cxx') }}              # [not win]
    - {{ compiler('m2w64_cxx') }}        # [win]
    - {{ posix }}filesystem              # [win]
    - {{ posix }}sed                     # [win]
    - {{ posix }}grep                    # [win]
    - {{ posix }}autoconf
    - {{ posix }}automake                # [not win]
    - {{ posix }}automake-wrapper        # [win]
    - pkg-config
    - {{ posix }}make
    - {{ posix }}coreutils               # [win]
    - {{ posix }}zip                     # [win]
  host:
    - r-base
    - r-htmltools
    - r-htmlwidgets >=1.6.0
    - r-jsonlite >=0.9.20
    - r-knitr >=1.33
    - r-magrittr
    - expat                              # [linux]
    - freetype
    - libglu                             # [linux]
    - libpng
    - xorg-libxfixes                     # [linux]
    - zlib                               # [win]
    - xorg-xorgproto                     # [linux]
    - libgl-devel                        # [linux]
    - xorg-libx11                        # [linux]
    - xorg-libxext                       # [linux]
    - xorg-libxrender                    # [linux]
    - libegl-devel                       # [linux]
    - xorg-libxau                        # [linux]
    - libdrm                             # [linux]
    - xorg-libxcomposite                 # [linux]
    - xorg-libxcursor                    # [linux]
    - xorg-libxi                         # [linux]
    - xorg-librandr                      # [linux]
    - xorg-libxscrnsaver                 # [linux]
    - xorg-libxtst                       # [linux]
  run:
    - r-base
    - r-htmltools
    - r-htmlwidgets >=1.6.0
    - r-jsonlite >=0.9.20
    - r-knitr >=1.33
    - r-magrittr
    - expat                              # [linux]
    - libglu                             # [linux]

test:
  commands:
    - $R -e "library('rgl')"           # [not win]

about:
  home: https://r-forge.r-project.org/projects/rgl/
  license: GPL-2.0-or-later
  summary: Provides medium to high level functions for 3D interactive graphics, including functions modelled on base graphics (plot3d(), etc.) as well as functions for constructing representations of geometric objects (cube3d(), etc.).  Output may be on screen using OpenGL, or to various standard 3D file formats
    including WebGL, PLY, OBJ, STL as well as 2D image formats, including PNG, Postscript, SVG, PGF.
  license_family: GPL
  license_file:
    - {{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-2
    - {{ environ["PREFIX"] }}/lib/R/share/licenses/GPL-3

extra:
  recipe-maintainers:
    - conda-forge/r
"""  # noqa

qt_recipe = """\
# This has become a metapacakge for qt-base and other related packages
{% set version = "5.15.15" %}

package:
  name: qt
  version: {{ version }}

# Add a dummy source so that the bot helps us keep this up to date
source:
  url: https://download.qt.io/official_releases/qt/{{ version.rpartition('.')[0] }}/{{ version }}/submodules/qtbase-everywhere-opensource-src-{{ version }}.tar.xz
  sha256: e5f941fecf694ecba97c550b45b0634e552166cc6c815bcfdc481edd62796ba1

build:
  number: 0
  run_exports:
    - {{ pin_subpackage('qt', max_pin='x.x') }}

requirements:
  run:
    - qt-main      {{ version }}.*
    # qt-webengine sometimes goes more out of sync due to
    # the fact that they release open source releases more frequently
    # qt-webengine does not support ppc64le
    # (https://github.com/conda-forge/qt-webengine-feedstock/pull/21)
    - qt-webengine {{ version }}.*  # [not ppc64le]

test:
  requires:
    - make                               # [unix]
    - {{ compiler('cxx') }}
    - {{ cdt('xorg-x11-proto-devel') }}  # [linux]
    - {{ cdt('libx11-devel') }}          # [linux]
    - {{ cdt('libxext-devel') }}         # [linux]
    - {{ cdt('libxrender-devel') }}      # [linux]
    - {{ cdt('mesa-libgl-devel') }}      # [linux]
    - {{ cdt('mesa-libegl-devel') }}     # [linux]
    - {{ cdt('mesa-dri-drivers') }}      # [linux]
    - {{ cdt('libxau-devel') }}          # [linux]
    - {{ cdt('alsa-lib-devel') }}        # [linux]
    - {{ cdt('gtk2-devel') }}            # [linux]
    - {{ cdt('gtkmm24-devel') }}         # [linux]
    - {{ cdt('libdrm-devel') }}          # [linux]
    - {{ cdt('libxcomposite-devel') }}   # [linux]
    - {{ cdt('libxcursor-devel') }}      # [linux]
    - {{ cdt('libxi-devel') }}           # [linux]
    - {{ cdt('libxrandr-devel') }}       # [linux]
    - {{ cdt('pciutils-devel') }}        # [linux]
    - {{ cdt('libxscrnsaver-devel') }}   # [linux]
    - {{ cdt('libxtst-devel') }}         # [linux]
    - {{ cdt('libselinux-devel') }}      # [linux]
    - {{ cdt('libxdamage') }}            # [linux]
    - {{ cdt('libxdamage-devel') }}      # [linux]
    - {{ cdt('libxfixes') }}             # [linux]
    - {{ cdt('libxfixes-devel') }}       # [linux]
    - {{ cdt('libxxf86vm') }}            # [linux]
    - {{ cdt('libxcb') }}                # [linux]
    - {{ cdt('expat-devel') }}           # [linux]
    - {{ cdt('pcre') }}                  # [linux and cdt_name != 'cos6']
    - {{ cdt('libglvnd-glx') }}          # [linux and cdt_name != 'cos6']
  files:
    - test/hello.pro
    - test/main-qtwebengine.cpp
    - test/main.cpp
    - test/main.qml
    - test/qml.qrc
    - test/qrc_qml.cpp
    - test/qtwebengine.pro
    - xcodebuild
    - xcrun
  commands:
    - if not exist %LIBRARY_BIN%\\Qt5WebEngine_conda.dll exit 1                  # [win]
    - if not exist %LIBRARY_BIN%\\Qt5Core_conda.dll exit 1                  # [win]
    - if not exist %LIBRARY_BIN%\\Qt5Gui_conda.dll exit 1                  # [win]
    - test -f $PREFIX/lib/libQt5WebEngine${SHLIB_EXT}                      # [unix and not ppc64le]
    - test -f $PREFIX/lib/libQt5Core${SHLIB_EXT}                               # [unix]
    - test -f $PREFIX/lib/libQt5Gui${SHLIB_EXT}                               # [unix]
    # sql plugin
    - test -f $PREFIX/plugins/sqldrivers/libqsqlite${SHLIB_EXT}            # [unix]
    - if not exist %LIBRARY_PREFIX%\\plugins\\sqldrivers\\qsqlite.dll exit 1  # [win]

about:
  home: http://qt-project.org
  license: LGPL-3.0-only
  license_file: LICENSE.LGPLv3
  summary: 'Qt is a cross-platform application and UI framework.'
  description: |
    Qt helps you create connected devices, UIs & applications that run
    anywhere on any device, on any operating system at any time.
  doc_url: http://doc.qt.io/
  dev_url: https://github.com/qtproject

extra:
  recipe-maintainers:
    - conda-forge/qt-main
"""  # noqa

qt_recipe_correct = """\
# This has become a metapacakge for qt-base and other related packages
{% set version = "5.15.15" %}

package:
  name: qt
  version: {{ version }}

# Add a dummy source so that the bot helps us keep this up to date
source:
  url: https://download.qt.io/official_releases/qt/{{ version.rpartition('.')[0] }}/{{ version }}/submodules/qtbase-everywhere-opensource-src-{{ version }}.tar.xz
  sha256: e5f941fecf694ecba97c550b45b0634e552166cc6c815bcfdc481edd62796ba1

build:
  number: 1
  run_exports:
    - {{ pin_subpackage('qt', max_pin='x.x') }}

requirements:
  run:
    - qt-main      {{ version }}.*
    # qt-webengine sometimes goes more out of sync due to
    # the fact that they release open source releases more frequently
    # qt-webengine does not support ppc64le
    # (https://github.com/conda-forge/qt-webengine-feedstock/pull/21)
    - qt-webengine {{ version }}.*  # [not ppc64le]

test:
  requires:
    - make                               # [unix]
    - {{ compiler('cxx') }}
    - xorg-xorgproto                     # [linux]
    - xorg-libx11                        # [linux]
    - xorg-libxext                       # [linux]
    - xorg-libxrender                    # [linux]
    - libgl-devel                        # [linux]
    - libegl-devel                       # [linux]
    - xorg-libxau                        # [linux]
    - alsa-lib                           # [linux]
    - gtk2                               # [linux]
    - libdrm                             # [linux]
    - xorg-libxcomposite                 # [linux]
    - xorg-libxcursor                    # [linux]
    - xorg-libxi                         # [linux]
    - xorg-librandr                      # [linux]
    - xorg-libxscrnsaver                 # [linux]
    - xorg-libxtst                       # [linux]
    - xorg-libxdamage                    # [linux]
    - xorg-libxfixes                     # [linux]
    - expat                              # [linux]
  files:
    - test/hello.pro
    - test/main-qtwebengine.cpp
    - test/main.cpp
    - test/main.qml
    - test/qml.qrc
    - test/qrc_qml.cpp
    - test/qtwebengine.pro
    - xcodebuild
    - xcrun
  commands:
    - if not exist %LIBRARY_BIN%\\Qt5WebEngine_conda.dll exit 1                  # [win]
    - if not exist %LIBRARY_BIN%\\Qt5Core_conda.dll exit 1                  # [win]
    - if not exist %LIBRARY_BIN%\\Qt5Gui_conda.dll exit 1                  # [win]
    - test -f $PREFIX/lib/libQt5WebEngine${SHLIB_EXT}                      # [unix and not ppc64le]
    - test -f $PREFIX/lib/libQt5Core${SHLIB_EXT}                               # [unix]
    - test -f $PREFIX/lib/libQt5Gui${SHLIB_EXT}                               # [unix]
    # sql plugin
    - test -f $PREFIX/plugins/sqldrivers/libqsqlite${SHLIB_EXT}            # [unix]
    - if not exist %LIBRARY_PREFIX%\\plugins\\sqldrivers\\qsqlite.dll exit 1  # [win]

about:
  home: http://qt-project.org
  license: LGPL-3.0-only
  license_file: LICENSE.LGPLv3
  summary: 'Qt is a cross-platform application and UI framework.'
  description: |
    Qt helps you create connected devices, UIs & applications that run
    anywhere on any device, on any operating system at any time.
  doc_url: http://doc.qt.io/
  dev_url: https://github.com/qtproject

extra:
  recipe-maintainers:
    - conda-forge/qt-main
"""  # noqa

connectome_recipe = """\
{% set name = "connectome-workbench" %}
{% set version = "2.0.1" %}
{% set build = 4 %}

{% set build = build + 100 %}  # [build_variant == "qt6"]

package:
  name: {{ name }}-split
  version: {{ version }}

source:
  url: https://github.com/Washington-University/workbench/archive/v{{ version }}.tar.gz
  sha256: c80bb248d1d25b36dd92112b9d3fb4585474e117c0c49dc8a222d859624f0376
  patches:
    - patches/0001-Import-cstdint-into-libCZI.h.patch
    - patches/0001-Fix-unsafe-narrowing.patch
    - patches/0001-chore-build-Find-QuaZip-library.patch

build:
  number: {{ build }}
  string: "{{ build_variant }}_h{{ PKG_HASH }}_{{ build }}"
  skip: true  # [osx or win]

requirements:
  build:
    - {{ compiler('cxx') }}
    - {{ stdlib('c') }}
    - cmake >=3.0
    - ninja
    - qwt
    # OpenMP
    - llvm-openmp  # [osx]
    - libgomp      # [linux]
    # libGL
    - {{ cdt('mesa-libgl-devel') }}  # [linux]
    - {{ cdt('mesa-dri-drivers') }}  # [linux]
    - {{ cdt('libxdamage') }}        # [linux]
    - {{ cdt('libxxf86vm') }}        # [linux]
    - {{ cdt('libxext') }}           # [linux]
  host:
    - noqt6                          # [build_variant == "qt5"]
    - noqt5                          # [build_variant == "qt6"]
    - qt-main                        # [build_variant == "qt5"]
    - qt6-main                       # [build_variant == "qt6"]
    - openssl
    # 1.2 is ABI compatible with 1.3, so this provides more flexibility
    - libzlib =1.2                   # [build_variant == "qt5"]
    # qt6 is build with 1.3
    - libzlib =1.3                   # [build_variant == "qt6"]
    - zlib
    # No qt6 build yet, use vendored
    - quazip                         # [build_variant == "qt5"]
    - freetype
    - libglu                         # [linux]
    - glew                           # [windows]
    - mesalib                        # [linux]

test:
  commands:
    - wb_view -help
    - wb_command -version
    - wb_shortcuts -help

outputs:
  - name: {{ name }}-gui
    # build/host requirements should exactly match the root requirements
    requirements:
      build:
        - {{ compiler('cxx') }}
        - {{ stdlib('c') }}
        - cmake >=3.0
        - ninja
        - qwt
        # OpenMP
        - llvm-openmp  # [osx]
        - libgomp      # [linux]
        # libGL
        - {{ cdt('mesa-libgl-devel') }}  # [linux]
        - {{ cdt('mesa-dri-drivers') }}  # [linux]
        - {{ cdt('libxdamage') }}        # [linux]
        - {{ cdt('libxxf86vm') }}        # [linux]
        - {{ cdt('libxext') }}           # [linux]
      host:
        - noqt6                          # [build_variant == "qt5"]
        - noqt5                          # [build_variant == "qt6"]
        - qt-main                        # [build_variant == "qt5"]
        - qt6-main                       # [build_variant == "qt6"]
        - openssl
        - libzlib =1.2                   # [build_variant == "qt5"]
        - libzlib =1.3                   # [build_variant == "qt6"]
        - zlib
        - quazip                         # [build_variant == "qt5"]
        - freetype
        - libglu                         # [linux]
        - glew                           # [windows]
        - mesalib                        # [linux]
      run:
        - libgl                          # [linux]
        - libglu                         # [linux]
        - mesalib                        # [linux]
    files:
      include:
        - bin/wb_view
    test:
      commands:
        - wb_view -help
  - name: {{ name }}-cli
    # build/host requirements should exactly match the root requirements
    requirements:
      build:
        - {{ compiler('cxx') }}
        - {{ stdlib('c') }}
        - cmake >=3.0
        - ninja
        - qwt
        # OpenMP
        - llvm-openmp  # [osx]
        - libgomp      # [linux]
        # libGL
        - {{ cdt('mesa-libgl-devel') }}  # [linux]
        - {{ cdt('mesa-dri-drivers') }}  # [linux]
        - {{ cdt('libxdamage') }}        # [linux]
        - {{ cdt('libxxf86vm') }}        # [linux]
        - {{ cdt('libxext') }}           # [linux]
      host:
        - noqt6                          # [build_variant == "qt5"]
        - noqt5                          # [build_variant == "qt6"]
        - qt-main                        # [build_variant == "qt5"]
        - qt6-main                       # [build_variant == "qt6"]
        - openssl
        - libzlib =1.2                   # [build_variant == "qt5"]
        - libzlib =1.3                   # [build_variant == "qt6"]
        - zlib
        - quazip                         # [build_variant == "qt5"]
        - freetype
        - libglu                         # [linux]
        - glew                           # [windows]
        - mesalib                        # [linux]
      run:
        - libgl                          # [linux]
        - libglu                         # [linux]
        - mesalib                        # [linux]
    files:
      include:
        - bin/wb_command
        - bin/wb_shortcuts
        - share/bash-completion/completions/*
    test:
      commands:
        - wb_command -version
        - wb_shortcuts -help
  - name: {{ name }}
    requirements:
      run:
        - {{ pin_subpackage('connectome-workbench-cli', exact=True) }}
        - {{ pin_subpackage('connectome-workbench-gui', exact=True) }}
    test:
      commands:
        - wb_view -help
        - wb_command -version
        - wb_shortcuts -help

about:
  home: https://www.humanconnectome.org/software/connectome-workbench
  summary: 'Neuroimaging utility for the Human Connectome Project'
  description: |
    Connectome Workbench is an open source, freely available visualization and discovery
    tool used to map neuroimaging data, especially data generated by the Human
    Connectome Project.
  license: GPL-2.0-only
  license_family: GPL
  license_file:
    - LICENSE
    - src/CZIlib/LICENSE
    - src/QxtCore/LICENSE_qxt
    - src/kloewe/cpuinfo/LICENSE
    - src/kloewe/dot/LICENSE
  doc_url: https://humanconnectome.org/software/workbench-command
  dev_url: https://github.com/Washington-University/workbench

extra:
  recipe-maintainers:
    - coalsont
    - effigies
"""  # noqa

connectome_recipe_correct = """\
{% set name = "connectome-workbench" %}
{% set version = "2.0.1" %}
{% set build = 5 %}

{% set build = build + 100 %}  # [build_variant == "qt6"]

package:
  name: {{ name }}-split
  version: {{ version }}

source:
  url: https://github.com/Washington-University/workbench/archive/v{{ version }}.tar.gz
  sha256: c80bb248d1d25b36dd92112b9d3fb4585474e117c0c49dc8a222d859624f0376
  patches:
    - patches/0001-Import-cstdint-into-libCZI.h.patch
    - patches/0001-Fix-unsafe-narrowing.patch
    - patches/0001-chore-build-Find-QuaZip-library.patch

build:
  number: {{ build }}
  string: "{{ build_variant }}_h{{ PKG_HASH }}_{{ build }}"
  skip: true  # [osx or win]

requirements:
  build:
    - {{ compiler('cxx') }}
    - {{ stdlib('c') }}
    - cmake >=3.0
    - ninja
    - qwt
    # OpenMP
    - llvm-openmp  # [osx]
    - libgomp      # [linux]
    # libGL
  host:
    - noqt6                          # [build_variant == "qt5"]
    - noqt5                          # [build_variant == "qt6"]
    - qt-main                        # [build_variant == "qt5"]
    - qt6-main                       # [build_variant == "qt6"]
    - openssl
    # 1.2 is ABI compatible with 1.3, so this provides more flexibility
    - libzlib =1.2                   # [build_variant == "qt5"]
    # qt6 is build with 1.3
    - libzlib =1.3                   # [build_variant == "qt6"]
    - zlib
    # No qt6 build yet, use vendored
    - quazip                         # [build_variant == "qt5"]
    - freetype
    - libglu                         # [linux]
    - glew                           # [windows]
    - mesalib                        # [linux]
    - libgl-devel                    # [linux]

test:
  commands:
    - wb_view -help
    - wb_command -version
    - wb_shortcuts -help

outputs:
  - name: {{ name }}-gui
    # build/host requirements should exactly match the root requirements
    requirements:
      build:
        - {{ compiler('cxx') }}
        - {{ stdlib('c') }}
        - cmake >=3.0
        - ninja
        - qwt
        # OpenMP
        - llvm-openmp  # [osx]
        - libgomp      # [linux]
        # libGL
      host:
        - noqt6                          # [build_variant == "qt5"]
        - noqt5                          # [build_variant == "qt6"]
        - qt-main                        # [build_variant == "qt5"]
        - qt6-main                       # [build_variant == "qt6"]
        - openssl
        - libzlib =1.2                   # [build_variant == "qt5"]
        - libzlib =1.3                   # [build_variant == "qt6"]
        - zlib
        - quazip                         # [build_variant == "qt5"]
        - freetype
        - libglu                         # [linux]
        - glew                           # [windows]
        - mesalib                        # [linux]
        - libgl-devel                    # [linux]
      run:
        - libgl                          # [linux]
        - libglu                         # [linux]
        - mesalib                        # [linux]
    files:
      include:
        - bin/wb_view
    test:
      commands:
        - wb_view -help
  - name: {{ name }}-cli
    # build/host requirements should exactly match the root requirements
    requirements:
      build:
        - {{ compiler('cxx') }}
        - {{ stdlib('c') }}
        - cmake >=3.0
        - ninja
        - qwt
        # OpenMP
        - llvm-openmp  # [osx]
        - libgomp      # [linux]
        # libGL
      host:
        - noqt6                          # [build_variant == "qt5"]
        - noqt5                          # [build_variant == "qt6"]
        - qt-main                        # [build_variant == "qt5"]
        - qt6-main                       # [build_variant == "qt6"]
        - openssl
        - libzlib =1.2                   # [build_variant == "qt5"]
        - libzlib =1.3                   # [build_variant == "qt6"]
        - zlib
        - quazip                         # [build_variant == "qt5"]
        - freetype
        - libglu                         # [linux]
        - glew                           # [windows]
        - mesalib                        # [linux]
        - libgl-devel                    # [linux]
      run:
        - libgl                          # [linux]
        - libglu                         # [linux]
        - mesalib                        # [linux]
    files:
      include:
        - bin/wb_command
        - bin/wb_shortcuts
        - share/bash-completion/completions/*
    test:
      commands:
        - wb_command -version
        - wb_shortcuts -help
  - name: {{ name }}
    requirements:
      run:
        - {{ pin_subpackage('connectome-workbench-cli', exact=True) }}
        - {{ pin_subpackage('connectome-workbench-gui', exact=True) }}
    test:
      commands:
        - wb_view -help
        - wb_command -version
        - wb_shortcuts -help

about:
  home: https://www.humanconnectome.org/software/connectome-workbench
  summary: 'Neuroimaging utility for the Human Connectome Project'
  description: |
    Connectome Workbench is an open source, freely available visualization and discovery
    tool used to map neuroimaging data, especially data generated by the Human
    Connectome Project.
  license: GPL-2.0-only
  license_family: GPL
  license_file:
    - LICENSE
    - src/CZIlib/LICENSE
    - src/QxtCore/LICENSE_qxt
    - src/kloewe/cpuinfo/LICENSE
    - src/kloewe/dot/LICENSE
  doc_url: https://humanconnectome.org/software/workbench-command
  dev_url: https://github.com/Washington-University/workbench

extra:
  recipe-maintainers:
    - coalsont
    - effigies
"""  # noqa


def test_cdt(tmp_path):
    run_test_migration(
        m=cdt_migrator,
        inp=freecad_recipe,
        output=freecad_recipe_correct,
        prb="This migrator will attempt to replace the CDT dependencies with regular conda-forge packages",
        kwargs={"new_version": "1.0.0"},
        mr_out={
            "migrator_name": "CDTMigrator",
            "migrator_version": 1,
            "name": "CDT Migrator",
        },
        tmp_path=tmp_path,
    )


def test_cdt_r_rgl(tmp_path):
    run_test_migration(
        m=cdt_migrator,
        inp=r_rgl_recipe,
        output=r_rgl_recipe_correct,
        prb="This migrator will attempt to replace the CDT dependencies with regular conda-forge packages",
        kwargs={"new_version": "1.0.0"},
        mr_out={
            "migrator_name": "CDTMigrator",
            "migrator_version": 1,
            "name": "CDT Migrator",
        },
        tmp_path=tmp_path,
    )


def test_cdt_qt(tmp_path):
    run_test_migration(
        m=cdt_migrator,
        inp=qt_recipe,
        output=qt_recipe_correct,
        prb="This migrator will attempt to replace the CDT dependencies with regular conda-forge packages",
        kwargs={"new_version": "1.0.0"},
        mr_out={
            "migrator_name": "CDTMigrator",
            "migrator_version": 1,
            "name": "CDT Migrator",
        },
        tmp_path=tmp_path,
    )


def test_cdt_connectome(tmp_path):
    run_test_migration(
        m=cdt_migrator,
        inp=connectome_recipe,
        output=connectome_recipe_correct,
        prb="This migrator will attempt to replace the CDT dependencies with regular conda-forge packages",
        kwargs={"new_version": "1.0.0"},
        mr_out={
            "migrator_name": "CDTMigrator",
            "migrator_version": 1,
            "name": "CDT Migrator",
        },
        tmp_path=tmp_path,
    )
