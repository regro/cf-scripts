from conda_forge_tick.utils import parse_meta_yaml, parse_munged_run_export

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


RECIPE_WEAK_STRONG = """\
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
    weak:
      - {{ pin_subpackage('slepc', max_pin='x.x') }} real_*  # comment
    strong:
      - {{ pin_subpackage('slepc', max_pin='x') }} imag_*  # comment

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


OPENCV_RECIPE = """\
{% set version = "4.8.0" %}
{% set major_version = version.split('.')[0] %}
{% set PY_VER_MAJOR = PY_VER.split('.')[0] %}
{% set PY_VER_MINOR = PY_VER.split('.')[1] %}

package:
  name: libopencv
  version: {{ version }}

source:
  - url: https://github.com/opencv/opencv/archive/{{ version }}.tar.gz
    fn: opencv-{{ version }}.tar.gz
    sha256: cbf47ecc336d2bff36b0dcd7d6c179a9bb59e805136af6b9670ca944aef889bd
    patches:
      # backport https://github.com/opencv/opencv/pull/21611 (unmerged as of 06/2023)
      - patches_opencv/0001-Add-installation-of-pip-metadata-from-cmake.patch
      - patches_opencv/0002-delete-lines-that-download-opencv.patch
      - patches_opencv/0003-find-pkgconfig-on-windows.patch
      - patches_opencv/0004-fix-detection-for-protobuf-23.x.patch
  - url: https://github.com/opencv/opencv_contrib/archive/{{ version }}.tar.gz
    fn: opencv_contrib-{{ version }}.tar.gz
    sha256: b4aef0f25a22edcd7305df830fa926ca304ea9db65de6ccd02f6cfa5f3357dbb
    folder: opencv_contrib
    patches:
      # Allow attempt to find HDF5 on cross-compile
      - patches_opencv_contrib/cmake_hdf5_xpile.patch
  - fn: test.avi
    url: https://github.com/opencv/opencv_extra/raw/master/testdata/highgui/video/VID00003-20100701-2204.avi
    sha256: 78884f64b564a3b06dc6ee731ed33b60c6d8cd864cea07f21d94ba0f90c7b310

build:
  number: 0
  string: py{{ PY_VER_MAJOR }}{{ PY_VER_MINOR }}h{{ PKG_HASH }}_{{ PKG_BUILDNUM }}
  run_exports:
    # https://abi-laboratory.pro/index.php?view=timeline&l=opencv
    # Things seem to change every patch versions, mostly the dnn module
    - {{ pin_subpackage('libopencv', max_pin='x.x.x') }}
  ignore_run_exports_from:
    - python

requirements:
  build:
    - python                                 # [build_platform != target_platform]
    - cross-python_{{ target_platform }}     # [build_platform != target_platform]
    - numpy                                  # [build_platform != target_platform]
    - libprotobuf                            # [build_platform != target_platform]
    # pkg-config is required to find ffpmeg
    - pkg-config
    - cmake
    - ninja
    - libgomp                        # [linux]
    # ICE when enabling this
    # - llvm-openmp                    # [osx]
    - {{ compiler('c') }}
    - {{ compiler('cxx') }}
    - sysroot_linux-64 2.17  # [linux64]
    - {{ cdt('mesa-libgl-devel') }}  # [linux]
    - {{ cdt('mesa-libegl-devel') }}  # [linux]
    - {{ cdt('mesa-dri-drivers') }}  # [linux]
    - {{ cdt('libselinux') }}        # [linux]
    - {{ cdt('libxdamage') }}        # [linux]
    - {{ cdt('libxfixes') }}         # [linux]
    - {{ cdt('libxxf86vm') }}        # [linux]
  host:
    - python
    - numpy
    - eigen =3.4.0
    - ffmpeg {{ ffmpeg }}=lgpl_*
    - freetype
    - glib                           # [unix]
    - harfbuzz
    - hdf5
    - jasper
    - libcblas
    - libiconv                       # [unix]
    - libjpeg-turbo
    - liblapack
    - liblapacke
    - libpng
    - libprotobuf
    - libtiff
    - libwebp
    - qt-main                        # [not osx and not ppc64le]
    - zlib
    - openvino                       # [not ppc64le]

test:
    requires:
      - {{ compiler('c') }}
      - {{ compiler('cxx') }}
      - pkg-config                    # [not win]
      # Test with the two currently supported lapack implementatons
      # One test done on different versions of python on each platform
      - liblapack * *openblas         # [py==36]
      - liblapack * *mkl              # [py==37 and linux64]
      - cmake
      - ninja
    files:
      - CMakeLists.txt
      - test.cpp
    commands:
        # Verify dynamic libraries on all systems
        {% set win_ver_lib = version|replace(".", "") %}
        # The bot doesn't support multiline jinja, so use
        # single line jinja.
        {% set opencv_libs = [] %}
        {{ opencv_libs.append("alphamat") or "" }}
        {{ opencv_libs.append("aruco") or "" }}
        {{ opencv_libs.append("bgsegm") or "" }}
        {{ opencv_libs.append("calib3d") or "" }}
        {{ opencv_libs.append("ccalib") or "" }}
        {{ opencv_libs.append("core") or "" }}
        {{ opencv_libs.append("datasets") or "" }}
        {{ opencv_libs.append("dnn_objdetect") or "" }}
        {{ opencv_libs.append("dnn_superres") or "" }}
        {{ opencv_libs.append("dnn") or "" }}
        {{ opencv_libs.append("dpm") or "" }}
        {{ opencv_libs.append("face") or "" }}
        {{ opencv_libs.append("features2d") or "" }}
        {{ opencv_libs.append("flann") or "" }}
        {{ opencv_libs.append("fuzzy") or "" }}
        {{ opencv_libs.append("gapi") or "" }}
        {{ opencv_libs.append("hfs") or "" }}
        {{ opencv_libs.append("highgui") or "" }}
        {{ opencv_libs.append("img_hash") or "" }}
        {{ opencv_libs.append("imgcodecs") or "" }}
        {{ opencv_libs.append("imgproc") or "" }}
        {{ opencv_libs.append("intensity_transform") or "" }}
        {{ opencv_libs.append("line_descriptor") or "" }}
        {{ opencv_libs.append("mcc") or "" }}
        {{ opencv_libs.append("ml") or "" }}
        {{ opencv_libs.append("objdetect") or "" }}
        {{ opencv_libs.append("optflow") or "" }}
        {{ opencv_libs.append("phase_unwrapping") or "" }}
        {{ opencv_libs.append("photo") or "" }}
        {{ opencv_libs.append("plot") or "" }}
        {{ opencv_libs.append("quality") or "" }}
        {{ opencv_libs.append("rapid") or "" }}
        {{ opencv_libs.append("reg") or "" }}
        {{ opencv_libs.append("rgbd") or "" }}
        {{ opencv_libs.append("saliency") or "" }}
        {{ opencv_libs.append("shape") or "" }}
        {{ opencv_libs.append("stereo") or "" }}
        {{ opencv_libs.append("stitching") or "" }}
        {{ opencv_libs.append("structured_light") or "" }}
        {{ opencv_libs.append("superres") or "" }}
        {{ opencv_libs.append("surface_matching") or "" }}
        {{ opencv_libs.append("text") or "" }}
        {{ opencv_libs.append("tracking") or "" }}
        {{ opencv_libs.append("video") or "" }}
        {{ opencv_libs.append("videoio") or "" }}
        {{ opencv_libs.append("videostab") or "" }}
        {{ opencv_libs.append("wechat_qrcode") or "" }}
        {{ opencv_libs.append("xfeatures2d") or "" }}
        {{ opencv_libs.append("ximgproc") or "" }}
        {{ opencv_libs.append("xobjdetect") or "" }}
        {{ opencv_libs.append("xphoto") or "" }}
        {{ opencv_libs.append("freetype") or "" }}
        - export MACOSX_DEPLOYMENT_TARGET={{ MACOSX_DEPLOYMENT_TARGET }}       # [osx]
        - export CONDA_BUILD_SYSROOT={{ CONDA_BUILD_SYSROOT }}                 # [osx]
        - OPENCV_FLAGS=`pkg-config --cflags opencv4`  # [unix]
        - $CXX -std=c++11 $RECIPE_DIR/test.cpp ${OPENCV_FLAGS} -o test   # [unix]
        - if [[ $(./test) != $PKG_VERSION ]]; then exit 1 ; fi                # [unix]
        {% for each_opencv_lib in opencv_libs %}
        - echo Testing for presence of {{ each_opencv_lib }}
        - test -f $PREFIX/lib/libopencv_{{ each_opencv_lib }}${SHLIB_EXT}                  # [unix]
        - if not exist %PREFIX%\\Library\\bin\\opencv_{{ each_opencv_lib }}{{ win_ver_lib }}.dll exit 1  # [win]
        {% endfor %}
        - test -f $PREFIX/lib/libopencv_bioinspired${SHLIB_EXT}  # [unix]
        - test -f $PREFIX/lib/libopencv_hdf${SHLIB_EXT}          # [unix]
        - mkdir -p cmake_build_test && pushd cmake_build_test
        - cmake -G "Ninja" ..
        - cmake --build . --config Release
        - popd

outputs:
  - name: libopencv
  - name: opencv
    build:
      string: py{{ PY_VER_MAJOR }}{{ PY_VER_MINOR }}h{{ PKG_HASH }}_{{ PKG_BUILDNUM }}
    requirements:
      host:
        # opencv    for pypy36 and python3.6
        # similarly for pypy37 and python3.7
        - python
      run:
        - {{ pin_subpackage('libopencv', exact=True) }}
        - {{ pin_subpackage('py-opencv', exact=True) }}
    test:
      commands:
        - echo "tested in other outputs"

  - name: py-opencv
    build:
      string: py{{ PY_VER_MAJOR }}{{ PY_VER_MINOR }}h{{ PKG_HASH }}_{{ PKG_BUILDNUM }}
      run_exports:
        # Should we even have this???
        # don't pin the python version so hard.
        # Actually, I have found pretty good compatibility in the python
        # package
        - {{ pin_subpackage('py-opencv') }}
    requirements:
      # There is no build script, but I just want it to think
      # that it needs python and numpy at build time
      host:
        - python
        - numpy
      run:
        - python
        - {{ pin_compatible('numpy') }}
        - {{ pin_subpackage('libopencv', exact=True) }}
    test:
      requires:
        # Test with the two currently supported lapack implementatons
        # One test done on different versions of python on each platform
        - liblapack * *openblas         # [py==39]
        - liblapack * *mkl              # [py==310 and linux64]
      imports:
        - cv2
        - cv2.xfeatures2d
        - cv2.freetype
      files:
        - run_py_test.py
        - color_palette_alpha.png
        - test_1_c1.jpg
      source_files:
        - test.avi
      commands:
        - python run_py_test.py
        - if [[ $($PYTHON -c 'import cv2; print(cv2.__version__)') != $PKG_VERSION ]]; then exit 1; fi  # [unix]
        - python -c "import cv2; assert 'Unknown' not in cv2.videoio_registry.getBackendName(cv2.CAP_V4L)"  # [linux]
        - python -c "import cv2, re; assert re.search('Lapack:\\s+YES', cv2.getBuildInformation())"
        - pip check
        - pip list
        - test $(pip list | grep opencv-python | wc -l) -eq 1  # [unix]
      requires:
        - pip


about:
  home: https://opencv.org/
  license: Apache-2.0
  license_family: Apache
  license_file: LICENSE
  summary: Computer vision and machine learning software library.
  dev_url: https://github.com/opencv/opencv
  doc_url: https://docs.opencv.org/{{ major_version }}.x/

extra:
  recipe-maintainers:
    - h-vetinari
    - xhochy
    - jakirkham
    - msarahan
    - patricksnape
    - zym1010
    - hajapy
    - ocefpaf
    - hmaarrfk
"""  # noqa


def test_parse_munged_run_export():
    meta_yaml = parse_meta_yaml(
        RECIPE,
        for_pinning=True,
    )
    assert meta_yaml["build"]["run_exports"] == [
        "__quote_plus__%7B%27package_name%27%3A+%27slepc%27%2C+%27max_pin%27%3A+%27x.x%27%7D__quote_plus__ real_*",
    ]
    assert parse_munged_run_export(meta_yaml["build"]["run_exports"][0]) == {
        "package_name": "slepc",
        "max_pin": "x.x",
    }


def test_parse_munged_run_export_weak_strong():
    meta_yaml = parse_meta_yaml(
        RECIPE_WEAK_STRONG,
        for_pinning=True,
    )
    assert parse_munged_run_export(meta_yaml["build"]["run_exports"]["weak"][0]) == {
        "package_name": "slepc",
        "max_pin": "x.x",
    }
    assert parse_munged_run_export(meta_yaml["build"]["run_exports"]["strong"][0]) == {
        "package_name": "slepc",
        "max_pin": "x",
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
                "__quote_plus__%7B%27package_name%27%3A+%27gnuradio-core%27%2C+%27max_pin%27%3A+%27x.x.x%27%7D__quote_plus__",
                "__quote_plus__%7B%27package_name%27%3A+%27gnuradio-pmt%27%2C+%27max_pin%27%3A+%27x.x.x%27%7D__quote_plus__",
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


def test_parse_munged_run_export_opencv():
    meta_yaml = parse_meta_yaml(
        OPENCV_RECIPE,
        for_pinning=True,
    )
    assert meta_yaml["build"]["run_exports"] == [
        "__quote_plus__%7B%27package_name%27%3A+%27libopencv%27%2C+%27max_pin%27%3A+%27x.x.x%27%7D__quote_plus__",
    ]
