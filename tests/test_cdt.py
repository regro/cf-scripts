import networkx as nx

from test_migrators import run_test_migration

from conda_forge_tick.migrators import CDTMigrator, Version

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
cdt_migrator = CDTMigrator(total_graph = TOTAL_GRAPH)

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
        - libgl-devel                # [linux]
        - xorg-libselinux            # [linux]
        - xorg-libxdamage            # [linux]
        - xorg-libxfixes             # [linux]
        - xorg-libxxf86vm            # [linux]
        - xorg-libxcb                # [linux]
        - xorg-libxext               # [linux]
        - xorg-x11-server-xvfb       # [linux]
        - xorg-libxau                # [linux]
        - xorg-libxi                 # [linux]
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


def test_cdt(tmp_path):
    run_test_migration(
        m=cdt_migrator,
        inp=freecad_recipe,
        output=freecad_recipe_correct,
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.0.0"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.0.0",
        },
        tmp_path=tmp_path,
    )
