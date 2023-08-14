from conda_forge_tick.utils import parse_munged_run_export, parse_meta_yaml


RECIPE = """\
{% set version = "3.19.1" %}
{% set sha256 = "280737e9ef762d7f0079ad3ad29913215c799ebf124651c723c1972f71fbc0db" %}
{% set build = 0 %}

package:
  name: slepc
  version: {{ version }}

source:
  url: http://slepc.upv.es/download/distrib/slepc-{{ version }}.tar.gz
  sha256: {{ sha256 }}

build:
  skip: true  # [win]
  number: {{ build }}
  string: real_h{{ PKG_HASH }}_{{ build }}
  run_exports:
    - {{ pin_subpackage('slepc', max_pin='x.x') }} real_*  # comment

requirements:
  run:
    - petsc
    - suitesparse

about:
  home: http://slepc.upv.es/
  summary: 'SLEPc: Scalable Library for Eigenvalue Problem Computations'
  license: BSD-2-Clause
  license_file: LICENSE.md
  license_family: BSD

extra:
  recipe-maintainers:
    - dalcinl
    - joseeroman
    - minrk

"""


ANOTHER_RECIPE = """\
{% set version = "3.10.7.0" %}
{% set prefix = "Library/" if win else "" %}
{% set lib = "" if win else "lib" %}

package:
  name: gnuradio
  version: {{ version }}

source:
  url: https://github.com/gnuradio/gnuradio/archive/refs/tags/v{{ version }}.tar.gz
  sha256: 55156650ada130600c70bc2ab38eee718fc1d23011be548471e888399f207ddc
  patches:
    - 0001-cmake-Install-python-wrapper-exe-for-scripts-on-Wind.patch
    - 0002-cmake-Don-t-generate-.pyc-and-.pyo-files.patch
    - 0003-grc-Remove-global_blocks_path-preference-and-use-pre.patch
    - 0004-filter-python-Drop-unused-args-argument-overriden-by.patch
    - 0005-cmake-runtime-Manually-set-the-pybind11-internal-bui.patch

build:
  number: 1

requirements:
  build:
    - {{ compiler('c') }}
    - {{ compiler('cxx') }}
    - cmake >=3.8
    - git
    - ninja
    - patch  # [osx]
    - pkg-config  # [not win]
    - thrift-compiler  # [not win]
    # cross-compilation requirements
    - python                              # [build_platform != target_platform]
    - cross-python_{{ target_platform }}  # [build_platform != target_platform]
    - pybind11                            # [build_platform != target_platform]
    - numpy                               # [build_platform != target_platform]
    - {{ cdt('mesa-dri-drivers') }}  # [linux]
    - {{ cdt('mesa-libgl-devel') }}  # [linux]

  host:
    - boost-cpp
    - click
    - click-plugins
    - codec2
    - fftw
    - fmt
    - gmp  # [not win]
    - gsl
    - libsndfile
    - libthrift  # [not win]
    - mako
    - mpir  # [win]
    - numpy
    - packaging
    - pip  # [win]
    - pybind11
    - pybind11-abi
    - python
    - spdlog
    - thrift  # [not win]
    - volk
  # gnuradio.audio
    - alsa-lib  # [linux]
    - jack  # [linux]
    - portaudio
  # gnuradio companion
    - gtk3
    - lxml
    - pygobject
    - pyyaml
    - jsonschema
  # gnuradio.iio
    - libiio
    - libad9361-iio
  # gnuradio.qtgui
    - pyqt
    - qt-main
    - qwt
  # gnuradio soapy
    - soapysdr
  # gnuradio.uhd
    - uhd
  # gnuradio.video_sdl
    - sdl
  # gnuradio.zeromq
    - cppzmq
    - zeromq

  run:
  # this is the metapackage that depends on all the subpackages
    - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
    - {{ pin_subpackage('gnuradio-core', exact=True) }}
    - {{ pin_subpackage('gnuradio-grc', exact=True) }}
    - {{ pin_subpackage('gnuradio-iio', exact=True) }}
    - {{ pin_subpackage('gnuradio-qtgui', exact=True) }}
    - {{ pin_subpackage('gnuradio-soapy', exact=True) }}
    - {{ pin_subpackage('gnuradio-uhd', exact=True) }}
    - {{ pin_subpackage('gnuradio-video-sdl', exact=True) }}
    - {{ pin_subpackage('gnuradio-zeromq', exact=True) }}
  # explicitly add python so that build string is generated correctly
    - python

test:
  downstreams:
    #- gnuradio-osmosdr
    #- gnuradio-satellites
  requires:
    - sqlite
  imports:
    - gnuradio.gr
    - gnuradio.iio
    - gnuradio.qtgui
    - gnuradio.soapy
    - gnuradio.uhd
    - gnuradio.video_sdl
    - gnuradio.zeromq
    - pmt

app:
  entry: gnuradio-companion
  icon: grc-icon.png
  summary: GNU Radio Companion

outputs:
  - name: gnuradio-pmt
    script: install_core.sh  # [not win]
    script: install_core.bat  # [win]
    files:
      - {{ prefix }}bin/{{ lib }}gnuradio-pmt.dll  # [win]
      - {{ prefix }}include/pmt
      - {{ prefix }}lib/{{ lib }}gnuradio-pmt*
      - {{ prefix }}lib/cmake/gnuradio/gnuradio-pmt*.cmake
      - {{ prefix }}lib/python{{ PY_VER }}/site-packages/pmt  # [unix]
      - Lib/site-packages/pmt  # [win]
    build:
      run_exports:
        - {{ pin_subpackage('gnuradio-pmt', max_pin='x.x.x') }}
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - cmake
        # conda-build needs native python to make .pyc files
        - python  # [build_platform != target_platform]
      host:
        - numpy
        - pybind11
        - pybind11-abi
        - python
        - volk
      run:
        - numpy
        - python
    test:
      commands:
        # verify that headers get installed
        - test -f $PREFIX/include/pmt/api.h  # [unix]
        - test -f $PREFIX/include/pmt/pmt_pool.h  # [unix]
        - test -f $PREFIX/include/pmt/pmt_serial_tags.h  # [unix]
        - test -f $PREFIX/include/pmt/pmt_sugar.h  # [unix]
        - test -f $PREFIX/include/pmt/pmt.h  # [unix]
        - if not exist %LIBRARY_INC%\\pmt\\api.h exit 1  # [win]
        - if not exist %LIBRARY_INC%\\pmt\\pmt_pool.h exit 1  # [win]
        - if not exist %LIBRARY_INC%\\pmt\\pmt_serial_tags.h exit 1  # [win]
        - if not exist %LIBRARY_INC%\\pmt\\pmt_sugar.h exit 1  # [win]
        - if not exist %LIBRARY_INC%\\pmt\\pmt.h exit 1  # [win]

        # verify that libraries get installed
        - test -f $PREFIX/lib/libgnuradio-pmt${SHLIB_EXT}  # [unix]
        - if not exist %LIBRARY_BIN%\\gnuradio-pmt.dll exit 1  # [win]
        - if not exist %LIBRARY_LIB%\\gnuradio-pmt.lib exit 1  # [win]
      imports:
        - pmt
    about:
      home: https://gnuradio.org/
      doc_url: https://gnuradio.org/doc/doxygen/
      dev_url: https://github.com/gnuradio/gnuradio
      license: GPL-3.0-or-later
      license_family: GPL
      license_file: COPYING
      summary: Polymorphic Type (PMT) library, bundled with GNU Radio
  - name: gnuradio-core
    script: install_core.sh  # [not win]
    script: install_core.bat  # [win]
    build:
      entry_points:
        - gr_modtool = gnuradio.modtool.cli.base:cli  # [win]
      run_exports:
        - {{ pin_subpackage('gnuradio-core', max_pin='x.x.x') }}
        - {{ pin_subpackage('gnuradio-pmt', max_pin='x.x.x') }}
      skip_compile_pyc:
        - '*/templates/*.py'
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - cmake
        # conda-build needs native python to make .pyc files
        - python  # [build_platform != target_platform]
      host:
        - alsa-lib  # [linux]
        - boost-cpp
        - codec2
        - fftw
        - fmt
        - gmp  # [not win]
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - gsl
        - jack  # [linux]
        - libsndfile
        - libthrift  # [not win]
        - mpir  # [win]
        - numpy
        - packaging
        - portaudio
        - pybind11
        - pybind11-abi
        - python
        - spdlog
        - thrift  # [not win]
        - volk
      run:
        - alsa-plugins  # [linux]
        - boost-cpp
        - click
        - click-plugins
        - fftw
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - mako
        - numpy
        - packaging
        - {{ pin_compatible('portaudio') }}
        - python
        - pyyaml
        # need setuptools because modtool uses pkg_resources
        - setuptools
    test:
      commands:
        - gnuradio-config-info -v --prefix --sysconfdir --prefsdir --userprefsdir --prefs --builddate --enabled-components --cc --cxx --cflags
        - gr_modtool --help
        - gr_read_file_metadata --help
      imports:
        - gnuradio.analog
        - gnuradio.audio
        - gnuradio.blocks
        - gnuradio.channels
        - gnuradio.digital
        - gnuradio.dtv
        - gnuradio.fec
        - gnuradio.fft
        - gnuradio.filter
        - gnuradio.gr
        - gnuradio.network
        - gnuradio.pdu
        - gnuradio.trellis
        - gnuradio.vocoder
        - gnuradio.wavelet
        - pmt
    about:
      home: https://gnuradio.org/
      doc_url: https://gnuradio.org/doc/doxygen/
      dev_url: https://github.com/gnuradio/gnuradio
      license: GPL-3.0-or-later
      license_family: GPL
      license_file: COPYING
      summary: GNU Radio core functionality and modules
  - name: gnuradio-grc
    script: install_grc.sh  # [not win]
    script: install_grc.bat  # [win]
    build:
      entry_points:
        - gnuradio-companion = gnuradio.grc.main:main  # [win]
        - grcc = gnuradio.grc.compiler:main  # [win]
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - cmake
        # conda-build needs native python to make .pyc files
        - python  # [build_platform != target_platform]
      host:
        - boost-cpp
        - fmt
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - gtk3
        - python
        - spdlog
      run:
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - jsonschema
        - lxml
        - menuinst  # [win]
        - pygobject
        - python
        - pyyaml
    test:
      requires:
        - coreutils  # [not win]
        - xvfbwrapper  # [linux]
      script: run_grc_test.py
      commands:
        - grcc "$PREFIX/share/gnuradio/examples/metadata/file_metadata_vector_sink.grc"  # [not win]
        - python "%PREFIX%\\Library\\bin\\grcc.py" "%PREFIX%\\Library\\share\\gnuradio\\examples\\metadata\\file_metadata_vector_sink.grc"  # [win]
        - python file_metadata_vector_sink.py  # [not win]
        - if not exist %PREFIX%\\Scripts\\gnuradio-companion.exe exit 1  # [win]
        - if not exist %PREFIX%\\Scripts\\grcc.exe exit 1  # [win]
        - xvfb-run -a -s "-screen 0 1024x768x24" bash -c 'timeout --preserve-status 30 gnuradio-companion "$PREFIX/share/gnuradio/examples/metadata/file_metadata_vector_sink.grc" || [[ $? -eq 143 ]]'  # [linux]
        - timeout --preserve-status 30 gnuradio-companion "$PREFIX/share/gnuradio/examples/metadata/file_metadata_vector_sink.grc" || [[ $? -eq 143 ]]  # [not linux and not win]
        - start gnuradio-companion "%PREFIX%\\Library\\share\\gnuradio\\examples\\metadata\\file_metadata_vector_sink.grc" && ping -n 30 127.0.0.1 >nul && taskkill /im gnuradio-companion.exe /f  # [win]
    about:
      home: https://gnuradio.org/
      doc_url: https://gnuradio.org/doc/doxygen/
      dev_url: https://github.com/gnuradio/gnuradio
      license: GPL-3.0-or-later
      license_family: GPL
      license_file: COPYING
      summary: GNU Radio Companion graphical flowgraph interface
  - name: gnuradio-iio
    script: install_iio.sh  # [not win]
    script: install_iio.bat  # [win]
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - cmake
        # conda-build needs native python to make .pyc files
        - python  # [build_platform != target_platform]
      host:
        - boost-cpp
        - fmt
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - libiio
        - libad9361-iio
        - python
        - spdlog
        - volk
      run:
        - boost-cpp
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - python
    test:
      imports:
        - gnuradio.iio
    about:
      home: https://gnuradio.org/
      doc_url: https://gnuradio.org/doc/doxygen/
      dev_url: https://github.com/gnuradio/gnuradio
      license: GPL-3.0-or-later
      license_family: GPL
      license_file: COPYING
      summary: GNU Radio module for using IIO devices
      description: >
        This module provides GNU Radio blocks for using IIO devices, including the PlutoSDR.
  - name: gnuradio-qtgui
    build:
      entry_points:
        - gr_filter_design = gnuradio.filter.filter_design:main
      ignore_run_exports_from:
        # see comment below in requirements: host
        - alsa-lib  # [linux]
    script: install_qtgui.sh  # [not win]
    script: install_qtgui.bat  # [win]
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - cmake
        # conda-build needs native python to make .pyc files
        - python  # [build_platform != target_platform]
      host:
        # alsa-lib dep added only because gnuradio-core and qt-main both depend
        # on it, and the outputs' run requirements can conflict if we don't
        # include it in the solve here
        - alsa-lib  # [linux]
        - boost-cpp
        - fmt
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - pyqt
        - python
        - qt-main
        - qwt
        - spdlog
        - volk
      run:
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - matplotlib-base
        - menuinst  # [win]
        - pyqt
        - pyqtgraph
        - python
        - {{ pin_compatible('qwt', max_pin='x.x') }}
        - scipy
    test:
      requires:
        - coreutils  # [not win]
      imports:
        - gnuradio.qtgui
      commands:
        - gr_filter_design --help
        - gr_plot --help
        - gr_plot_const --help
        - gr_plot_fft --help
        - gr_plot_iq --help
        - gr_plot_psd --help
        # needs pyqt-qwt which is not on conda-forge
        #- gr_plot_qt --help
        - QT_DEBUG_PLUGINS=1 xvfb-run -a -s "-screen 0 1024x768x24" bash -c 'timeout --preserve-status 10 gr_filter_design || [[ $? -eq 143 ]]'  # [linux]
        - QT_DEBUG_PLUGINS=1 timeout --preserve-status 10 gr_filter_design || [[ $? -eq 143 ]]  # [not linux and not win]
        - start gr_filter_design && ping -n 30 127.0.0.1 >nul && taskkill /im gr_filter_design.exe /f  # [win]
    about:
      home: https://gnuradio.org/
      doc_url: https://gnuradio.org/doc/doxygen/
      dev_url: https://github.com/gnuradio/gnuradio
      license: GPL-3.0-or-later
      license_family: GPL
      license_file: COPYING
      summary: GNU Radio QT module providing graphical components
  - name: gnuradio-soapy
    script: install_soapy.sh  # [not win]
    script: install_soapy.bat  # [win]
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - cmake
        # conda-build needs native python to make .pyc files
        - python  # [build_platform != target_platform]
      host:
        - boost-cpp
        - fmt
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - python
        - soapysdr
        - spdlog
      run:
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - python
    test:
      imports:
        - gnuradio.soapy
    about:
      home: https://gnuradio.org/
      doc_url: https://gnuradio.org/doc/doxygen/
      dev_url: https://github.com/gnuradio/gnuradio
      license: GPL-3.0-or-later
      license_family: GPL
      license_file: COPYING
      summary: GNU Radio SoapySDR module for using a variety of SDR devices
      description: >
        This module provides GNU Radio source and sink blocks for a variety of SDR devices using SoapySDR, a generalized C/C++ library which provides abstraction in interfacing with different SDR devices and vendors.
  - name: gnuradio-uhd
    script: install_uhd.sh  # [not win]
    script: install_uhd.bat  # [win]
    build:
      entry_points:
        - uhd_siggen = gnuradio.uhd.uhd_siggen_base:main  # [win]
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - cmake
        # conda-build needs native python to make .pyc files
        - python  # [build_platform != target_platform]
      host:
        - boost-cpp
        - fmt
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - python
        - spdlog
        - uhd
        - volk
      run:
        - boost-cpp
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - pyqt
        - python
    test:
      commands:
        - uhd_siggen -h
      imports:
        - gnuradio.uhd
    about:
      home: https://gnuradio.org/
      doc_url: https://gnuradio.org/doc/doxygen/
      dev_url: https://github.com/gnuradio/gnuradio
      license: GPL-3.0-or-later
      license_family: GPL
      license_file: COPYING
      summary: GNU Radio UHD module for Ettus USRP radios
  - name: gnuradio-video-sdl
    script: install_video_sdl.sh  # [not win]
    script: install_video_sdl.bat  # [win]
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - cmake
        # conda-build needs native python to make .pyc files
        - python  # [build_platform != target_platform]
      host:
        - boost-cpp
        - fmt
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - python
        - sdl
        - spdlog
      run:
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - python
    test:
      imports:
        - gnuradio.video_sdl
    about:
      home: https://gnuradio.org/
      doc_url: https://gnuradio.org/doc/doxygen/
      dev_url: https://github.com/gnuradio/gnuradio
      license: GPL-3.0-or-later
      license_family: GPL
      license_file: COPYING
      summary: GNU Radio SDL module providing video components
  - name: gnuradio-zeromq
    script: install_zeromq.sh  # [not win]
    script: install_zeromq.bat  # [win]
    requirements:
      build:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - cmake
        # conda-build needs native python to make .pyc files
        - python  # [build_platform != target_platform]
      host:
        - boost-cpp
        - cppzmq
        - fmt
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - python
        - spdlog
        - zeromq
      run:
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - {{ pin_subpackage('gnuradio-pmt', exact=True) }}
        - python
        - pyzmq
    test:
      imports:
        - gnuradio.zeromq
    about:
      home: https://gnuradio.org/
      doc_url: https://gnuradio.org/doc/doxygen/
      dev_url: https://github.com/gnuradio/gnuradio
      license: GPL-3.0-or-later
      license_family: GPL
      license_file: COPYING
      summary: GNU Radio ZeroMQ module for message passing functionality
  - name: gnuradio-build-deps
    build:
      string: {{ (pin_subpackage('gnuradio-core', exact=True) if (pin_subpackage('gnuradio-core', exact=True) is string) else '').partition(' ')[-1].partition(' ')[-1] }}
    requirements:
      host:
        # need to populate host to get complete build string (why?)
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - fmt
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
        - spdlog
      run:
        - {{ compiler('c') }}
        - {{ compiler('cxx') }}
        - cmake
        - ninja
        - numpy {{ numpy }}.*
        - pip  # [win]
        - pkg-config
        - pybind11
      run_constrained:
        - {{ pin_subpackage('gnuradio-core', exact=True) }}
    test:
      commands:
        - cmake --help
    about:
      home: https://gnuradio.org/
      doc_url: https://gnuradio.org/doc/doxygen/
      dev_url: https://github.com/gnuradio/gnuradio
      license: GPL-3.0-or-later
      license_family: GPL
      license_file: COPYING
      summary: Meta-package for GNU Radio deps used to manually build OOT modules
      description: >
        Install this meta-package into an environment with `gnuradio` or `gnuradio-core` in order to be able to build out-of-tree modules manually. DO NOT USE THIS IN CONDA RECIPES.
  # need an output with a script defined to work-around "empty" output detection
  # with python in both build (due to ninja) and host environments
  - name: gnuradio
    script: install_gnuradio.sh  # [not win]
    script: install_gnuradio.bat  # [win]

about:
  home: https://gnuradio.org/
  license: GPL-3.0-or-later
  license_family: GPL
  license_file: COPYING
  summary: The free and open software radio ecosystem
  description: >
    GNU Radio is a free software development toolkit that provides the signal processing runtime and processing blocks to implement software radios using readily-available, low-cost external RF hardware and commodity processors. It is widely used in hobbyist, academic and commercial environments to support wireless communications
    research as well as to implement real-world radio systems.

    GNU Radio applications are primarily written using the Python programming language, while the supplied, performance-critical signal processing path is implemented in C++ using processor floating point extensions where available. Thus, the developer is able to implement real-time, high- throughput radio systems in a simple-to-use,
    rapid-application-development environment.

  doc_url: https://gnuradio.org/doc/doxygen/
  dev_url: https://github.com/gnuradio/gnuradio

extra:
  recipe-maintainers:
    - ryanvolz
"""  # noqa


def test_parse_munged_run_export():
    meta_yaml = parse_meta_yaml(
        RECIPE,
        for_pinning=True,
    )
    assert meta_yaml["build"]["run_exports"] == [
        "__dict__'package_name'@$$'slepc',$$'max_pin'@$$'x.x'__dict__ real_*",
    ]
    assert parse_munged_run_export(meta_yaml["build"]["run_exports"][0]) == {
        "package_name": "slepc",
        "max_pin": "x.x",
    }


def test_parse_munged_run_export_gnuradio():
    meta_yaml = parse_meta_yaml(
        ANOTHER_RECIPE,
        for_pinning=True,
    )
    for out in meta_yaml["outputs"]:
        if out["name"] == "gnuradio-core":
            assert len(out["build"]["run_exports"]) == 2
            assert out["build"]["run_exports"] == [
                "__dict__'package_name'@$$'gnuradio-core',$$'max_pin'@$$'x.x.x'__dict__",
                "__dict__'package_name'@$$'gnuradio-pmt',$$'max_pin'@$$'x.x.x'__dict__",
            ]
            assert [
                parse_munged_run_export(out["build"]["run_exports"][0]),
                parse_munged_run_export(out["build"]["run_exports"][1]),
            ] == [
                {
                    "package_name": "gnuradio-core",
                    "max_pin": "x.x.x",
                },
                {
                    "package_name": "gnuradio-pmt",
                    "max_pin": "x.x.x",
                },
            ]
