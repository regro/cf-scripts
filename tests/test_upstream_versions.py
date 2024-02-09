import logging
import os
from unittest.mock import Mock, patch

import pytest
from conda.models.version import VersionOrder
from flaky import flaky

from conda_forge_tick.lazy_json_backends import LazyJson
from conda_forge_tick.update_sources import (
    NPM,
    NVIDIA,
    AbstractSource,
    Github,
    PyPI,
    RawURL,
    next_version,
)
from conda_forge_tick.update_upstream_versions import (
    filter_nodes_for_job,
    get_latest_version,
    ignore_version,
    include_node,
)
from conda_forge_tick.utils import parse_meta_yaml

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")

sample_npm = """
{% set name = "configurable-http-proxy" %}
{% set version = "3.1.0" %}
{% set node_version = os.environ.get('NODEJS_VERSION') or '6.*' %}
{% set node_major = node_version.split('.')[0] %}
{% set build = 1 %}

package:
  name: {{ name }}
  version: {{ version }}

source:
  fn: {{ name }}-{{ version }}.tar.gz
  url: https://registry.npmjs.org/{{ name }}/-/{{ name }}-{{ version }}.tgz
  sha256: eb41627ed15505261dbbb48eb4b9f1c6cd31a884b0f1afa9001a671b67262ad0

build:
  number: {{ build }}
  string: "node{{node_major}}_{{ build}}"
  script: npm pack; npm install -g {{name}}-{{version}}.tgz  # [not win]

requirements:
  build:
    - nodejs {{node_version}}
  run:
    - nodejs {{node_version}}

test:
  commands:
    - configurable-http-proxy -h

about:
  home: https://github.com/jupyterhub/configurable-http-proxy
  license: BSD 3-Clause
  license_file: LICENSE
  summary: node-http-proxy plus a REST API

extra:
  recipe-maintainers:
    - minrk
    - willingc
"""

sample_npm_response = """
{
  "_id": "configurable-http-proxy",
  "_rev": "49-72888ab1d40c9ffb823e9ef7fb94292a",
  "description": "A configurable-on-the-fly HTTP Proxy",
  "dist-tags": {
    "latest": "3.1.1"
  },
  "name": "configurable-http-proxy",
  "versions": {
    "3.1.1": {
      "_id": "configurable-http-proxy@3.1.1",
      "_nodeVersion": "8.7.0",
      "_npmOperationalInternal": {
        "host": "s3://npm-registry-packages",
        "tmp": "tmp/configurable-http-proxy-3.1.1.tgz_1516041466749_0.20442280289717019"
      },
      "_npmUser": {
        "email": "benjaminrk@gmail.com",
        "name": "minrk"
      },
      "_npmVersion": "5.4.2",
      "author": {
        "name": "Jupyter Developers"
      },
      "bin": {
        "configurable-http-proxy": "bin/configurable-http-proxy"
      },
      "bugs": {
        "url": "https://github.com/jupyterhub/configurable-http-proxy/issues"
      },
      "dependencies": {
        "commander": "~2.13.0",
        "http-proxy": "~1.16.2",
        "lynx": "^0.2.0",
        "strftime": "~0.10.0",
        "winston": "~2.4.0"
      },
      "description": "A configurable-on-the-fly HTTP Proxy",
      "devDependencies": {
        "jasmine": "^2.5.1",
        "jshint": "^2.9.2",
        "nyc": "^11.0.2",
        "prettier": "^1.4.4",
        "request": "^2.81.0",
        "request-promise-native": "^1.0.4",
        "ws": "^4.0.0"
      },
      "directories": {
      },
      "dist": {
        "integrity": "sha512-e+fxBy5cCayuNpxt3tcigBIuFsU/+oN48eK3aQtCBV12glavbBMxJa3ut2AEDHhXa/g3pC8r2BorKthrofHGRw==",
        "shasum": "bc386574c519efeb8437960234d598be8fdd2030",
        "tarball": "https://registry.npmjs.org/configurable-http-proxy/-/configurable-http-proxy-3.1.1.tgz"
      },
      "engineStrict": true,
      "engines": {
        "node": ">= 4.0"
      },
      "files": [
        "index.js",
        "lib/configproxy.js",
        "lib/store.js",
        "lib/trie.js",
        "lib/error/*.html",
        "bin/configurable-http-proxy"
      ],
      "gitHead": "91eb3e6c0e21a23d0c34277df42dfcbe71d52b8c",
      "homepage": "https://github.com/jupyterhub/configurable-http-proxy#readme",
      "license": "BSD-3-Clause",
      "main": "index.js",
      "maintainers": [
        {
          "email": "rgbkrk@gmail.com",
          "name": "rgbkrk"
        },
        {
          "email": "benjaminrk@gmail.com",
          "name": "minrk"
        }
      ],
      "name": "configurable-http-proxy",
      "repository": {
        "type": "git",
        "url": "git+https://github.com/jupyterhub/configurable-http-proxy.git"
      },
      "scripts": {
        "codecov": "nyc report --reporter=lcov && codecov",
        "coverage-html": "nyc report --reporter=html",
        "fmt": "prettier --write *.js bin/* lib/*.js test/*.js --trailing-comma es5 --print-width 100",
        "lint": "jshint bin/ lib/ test/",
        "test": "nyc jasmine JASMINE_CONFIG_PATH=test/jasmine.json"
      },
      "version": "3.1.1"
    }
  }
}
"""  # noqa

sample_spams = """\
{% set version = "2.6.1" %}
{% set date = "2017-12-08" %}
{% set file_num = "37237" %}


package:
  name: python-spams
  version: {{ version }}

source:
  fn: spams-python-{{ version }}.tar.gz
  url: http://spams-devel.gforge.inria.fr/hitcounter2.php?file={{ file_num }}/spams-python-v{{ version }}-svn{{ date }}.tar.gz
  sha256: 3012529c0461bd777228dce53c880f2a5fa2aaf22b5d673a1f22045a63f4d8bc

  patches:
    # patch setup.py to link to LLVM's OpenMP library instead of GCC's.
    - llvm_openmp_setup.py.patch  # [osx]
    # array creation requires integers for shape specification.
    - spams.py.patch

build:
  skip: true  # [win or (osx and cxx_compiler == "toolchain_cxx")]
  number: 1204
  detect_binary_files_with_prefix: true
  features:

requirements:
  build:
    - {{ compiler("cxx") }}
    - llvm-openmp                    # [osx]
  host:
    - libblas
    - liblapack
    - python
    - pip
    - llvm-openmp                    # [osx]
    - numpy
  run:
    - python
    - llvm-openmp                    # [osx]
    - {{ pin_compatible('numpy') }}
    - scipy
    - six

test:
  source_files:
    # Test data
    - extdata/boat.png
    - extdata/lena.png
    # Test suite
    - test_decomp.py
    - test_dictLearn.py
    - test_linalg.py
    - test_prox.py
    - test_spams.py
    - test_utils.py
  requires:
    - pillow
  imports:
    - spams

about:
  home: http://spams-devel.gforge.inria.fr/
  license: GPL 3
  license_family: GPL
  license_file: LICENSE.txt
  summary: An optimization toolbox for solving various sparse estimation problems.

extra:
  recipe-maintainers:
    - jakirkham
    - zym1010
"""  # noqa

sample_cmake_no_system = """\
{% set version = "3.16.4" %}

package:
  name: cmake-no-system
  version: {{ version }}

source:
  url: https://github.com/Kitware/CMake/releases/download/v{{ version }}/cmake-{{ version }}.tar.gz
  sha256: 9bcc8c114d9da603af9512083ed7d4a39911d16105466beba165ba8fe939ac2c
  patches:
    - patches/3.16.2/0001-find_-Add-debug-logging-infrastructure.patch
    - patches/3.16.2/0002-find_-Use-debug-logging-infrastructure.patch
    - patches/3.16.2/0003-Add-more-debug-logging-to-cmFindCommon.patch

build:
  number: 0
  skip: True  # [win]

requirements:
  build:
    - {{ compiler('c') }}
    - {{ compiler('cxx') }}
    - make
    - patch

test:
  commands:
    - cmake --version
    - ctest --version
    - cpack --version

about:
  home: http://www.cmake.org/
  license: BSD-3-Clause
  license_family: BSD
  license_file:
    - Copyright.txt
    - Utilities/cmbzip2/LICENSE
    - Utilities/cmcurl/COPYING
    - Utilities/cmexpat/COPYING
    - Utilities/cmjsoncpp/LICENSE
    - Utilities/cmlibarchive/COPYING
    - Utilities/cmliblzma/COPYING
    - Utilities/cmlibrhash/COPYING
    - Utilities/cmlibuv/LICENSE
    - Utilities/cmzlib/Copyright.txt
    - Utilities/cmzstd/LICENSE
  summary: CMake built without system libraries for use when building CMake dependencies.

extra:
  recipe-maintainers:
    - jjhelmus
    - beckermr
"""  # noqa

latest_url_npm_test_list = [
    (
        "configurable-http-proxy",
        sample_npm,
        "3.1.0",
        "3.1.1",
        NPM(),
        {"https://registry.npmjs.org/configurable-http-proxy": sample_npm_response},
    ),
]

latest_url_rawurl_test_list = [
    (
        "python-spams",
        sample_spams,
        "2.6.1",
        False,
        RawURL(),
        {},
    ),
    (
        "cmake-no-system",
        sample_cmake_no_system,
        "3.16.4",
        # represents any version in the test
        # which exact one we get changes due to internet failures
        None,
        RawURL(),
        {},
    ),
]


@pytest.mark.parametrize(
    "attrs",
    [
        {"key": "value"},
        {"conda-forge.yml": {"key": "value"}},
        {"conda-forge.yml": {"bot": {"key": "value"}}},
        {"conda-forge.yml": {"bot": {"version_updates": {"key": "value"}}}},
        {"conda-forge.yml": {"bot": {"version_updates": {"exclude": []}}}},
        {
            "conda-forge.yml": {
                "bot": {
                    "version_updates": {
                        "exclude": ["12.3", "1.23", "1.2", "2.3", "1.2.3.4"],
                    },
                },
            },
        },
    ],
)
def test_ignore_version_false(attrs):
    assert ignore_version(attrs, "1.2.3") is False


@pytest.mark.parametrize(
    "attrs",
    [
        {"conda-forge.yml": {"bot": {"version_updates": {"exclude": ["1.2.3"]}}}},
        {
            "conda-forge.yml": {
                "bot": {"version_updates": {"exclude": ["3.2.1", "1.2.3"]}},
            },
        },
        {
            "conda-forge.yml": {
                "bot": {"version_updates": {"exclude": ["1.2.3", "3.2.1"]}},
            },
        },
    ],
)
@pytest.mark.parametrize("version", ["1.2.3", "1.2-3"])
def test_ignore_version_true(attrs, version):
    assert ignore_version(attrs, version) is True


@pytest.mark.parametrize(
    "name, inp, curr_ver, ver, source, urls",
    latest_url_npm_test_list,
)
def test_latest_version_npm(
    name,
    inp,
    curr_ver,
    ver,
    source,
    urls,
    requests_mock,
    tmpdir,
):
    pmy = LazyJson(os.path.join(str(tmpdir), "cf-scripts-test.json"))
    with pmy as _pmy:
        _pmy.update(parse_meta_yaml(inp)["source"])
        _pmy.update(
            {
                "feedstock_name": name,
                "version": curr_ver,
                "raw_meta_yaml": inp,
                "meta_yaml": parse_meta_yaml(inp),
            },
        )
    [requests_mock.get(url, text=text) for url, text in urls.items()]
    attempt = get_latest_version(name, pmy, [source])
    if ver is None:
        assert attempt["new_version"] is not False
        assert attempt["new_version"] != curr_ver
        assert VersionOrder(attempt["new_version"]) > VersionOrder(curr_ver)
    elif ver is False:
        assert attempt["new_version"] is ver
    else:
        assert ver == attempt["new_version"]


@pytest.mark.parametrize(
    "name, inp, curr_ver, ver, source, urls",
    latest_url_rawurl_test_list,
)
@flaky
def test_latest_version_rawurl(name, inp, curr_ver, ver, source, urls, tmpdir):
    pmy = LazyJson(os.path.join(tmpdir, "cf-scripts-test.json"))
    with pmy as _pmy:
        _pmy.update(parse_meta_yaml(inp)["source"])
        _pmy.update(
            {
                "feedstock_name": name,
                "version": curr_ver,
                "raw_meta_yaml": inp,
                "meta_yaml": parse_meta_yaml(inp),
            },
        )
    attempt = get_latest_version(name, pmy, [source])
    if ver is None:
        assert attempt["new_version"] is not False
        assert attempt["new_version"] != curr_ver
        assert VersionOrder(attempt["new_version"]) > VersionOrder(curr_ver)
    elif ver is False:
        assert attempt["new_version"] is ver
    else:
        assert ver == attempt["new_version"]


def test_latest_version_ca_policy_lcg(caplog):
    assert get_latest_version("ca-policy-lcg", {}, [RawURL()]) == {"new_version": False}
    assert "ca-policy-lcg" in caplog.text
    assert "manually excluded" in caplog.text


def test_latest_version_version_sources_no_error(caplog):
    caplog.set_level(logging.DEBUG)

    source_a = Mock(AbstractSource)
    source_a.name = "this Is Source A"

    source_b = Mock(AbstractSource)
    source_b.name = "Source b it Is"

    attrs = {
        "conda-forge.yml": {
            "bot": {
                "version_updates": {
                    "sources": ["source B it is", "source c"],
                },
            },
        },
    }

    source_b.get_url.return_value = "https://source-b.com"
    source_b.get_version.return_value = "1.2.3"

    with patch(
        "conda_forge_tick.update_upstream_versions.ignore_version", return_value=False
    ) as ignore_version_mock:
        result = get_latest_version("crazy-package", attrs, [source_a, source_b])

    # source c is not a valid source, source a does not appear in the list
    assert (
        "crazy-package requests version source 'source c' which is not available"
        in caplog.text
    )
    assert (
        "crazy-package defines the following custom version sources: ['Source b it Is']"
        in caplog.text
    )
    assert "we skip the following sources: ['this Is Source A']" in caplog.text

    assert (
        "Fetching latest version for crazy-package from Source b it Is" in caplog.text
    )

    source_b.get_url.assert_called_once_with(attrs)
    assert "Using URL https://source-b.com" in caplog.text

    source_b.get_version.assert_called_once_with("https://source-b.com")
    assert "Found version 1.2.3 on Source b it Is" in caplog.text

    ignore_version_mock.assert_called_once_with(attrs, "1.2.3")

    assert result == {"new_version": "1.2.3"}


def test_latest_version_skip_error_success(caplog):
    caplog.set_level(logging.DEBUG)

    source_a = Mock(AbstractSource)
    source_a.name = "source a"
    source_a.get_url.return_value = "https://source-a.com"
    source_a.get_version.side_effect = Exception("source a error")

    source_b = Mock(AbstractSource)
    source_b.name = "source b"
    source_b.get_url.return_value = "https://source-b.com"
    source_b.get_version.return_value = "1.2.3"

    with patch(
        "conda_forge_tick.update_upstream_versions.ignore_version", return_value=False
    ):
        result = get_latest_version("crazy-package", {}, [source_a, source_b])

    assert "Using URL https://source-a.com" in caplog.text
    assert (
        "An exception occurred while fetching crazy-package from source a:"
        in caplog.text
    )
    assert "source a error" in caplog.text

    assert result == {"new_version": "1.2.3"}


def test_latest_version_error_and_no_new_version(caplog):
    caplog.set_level(logging.DEBUG)

    source_a = Mock(AbstractSource)
    source_a.name = "source a"
    source_a.get_url.return_value = "https://source-a.com"
    source_a.get_version.side_effect = ZeroDivisionError("source a error")

    source_b = Mock(AbstractSource)
    source_b.name = "source b"
    source_b.get_url.return_value = "https://source-b.com"
    source_b.get_version.return_value = None

    with pytest.raises(ZeroDivisionError):
        get_latest_version("crazy-package", {}, [source_a, source_b])

    assert "Using URL https://source-a.com" in caplog.text
    assert (
        "An exception occurred while fetching crazy-package from source a:"
        in caplog.text
    )
    assert "source a error" in caplog.text

    assert "Fetching latest version for crazy-package from source b" in caplog.text
    assert "Upstream: Could not find version on source b" in caplog.text

    assert "Cannot find version on any source, exceptions occurred" in caplog.text


@pytest.mark.parametrize(
    "in_ver, ver_test",
    [
        ("8.1", ["8.2", "8.3", "9.0", "9.1", "10.0", "10.1"]),
        (
            "8.1.5",
            [
                "8.1.6",
                "8.1.7",
                "8.2.0",
                "8.2.1",
                "8.3.0",
                "8.3.1",
                "9.0.0",
                "9.0.1",
                "9.1.0",
                "10.0.0",
                "10.0.1",
                "10.1.0",
            ],
        ),
        ("8_1", ["8_2", "8_3", "9_0", "9_1", "10_0", "10_1"]),
        (
            "8_1_5",
            [
                "8_1_6",
                "8_1_7",
                "8_2_0",
                "8_2_1",
                "8_3_0",
                "8_3_1",
                "9_0_0",
                "9_0_1",
                "9_1_0",
                "10_0_0",
                "10_0_1",
                "10_1_0",
            ],
        ),
        ("8-1", ["8-2", "8-3", "9-0", "9-1", "10-0", "10-1"]),
        (
            "8-1-5",
            [
                "8-1-6",
                "8-1-7",
                "8-2-0",
                "8-2-1",
                "8-3-0",
                "8-3-1",
                "9-0-0",
                "9-0-1",
                "9-1-0",
                "10-0-0",
                "10-0-1",
                "10-1-0",
            ],
        ),
        (
            "8.1-10",
            [
                "8.1-11",
                "8.1-12",
                "8.2-0",
                "8.2-1",
                "8.3-0",
                "8.3-1",
                "9.0-0",
                "9.0-1",
                "9.1-0",
                "10.0-0",
                "10.0-1",
                "10.1-0",
            ],
        ),
        (
            "8.1_10",
            [
                "8.1_11",
                "8.1_12",
                "8.2_0",
                "8.2_1",
                "8.3_0",
                "8.3_1",
                "9.0_0",
                "9.0_1",
                "9.1_0",
                "10.0_0",
                "10.0_1",
                "10.1_0",
            ],
        ),
        (
            "10.8.1-10",
            [
                "10.8.1-11",
                "10.8.1-12",
                "10.8.2-0",
                "10.8.2-1",
                "10.8.3-0",
                "10.8.3-1",
                "10.9.0-0",
                "10.9.0-1",
                "10.9.1-0",
                "10.10.0-0",
                "10.10.0-1",
                "10.10.1-0",
                "11.0.0-0",
                "11.0.0-1",
                "11.0.1-0",
                "11.1.0-0",
                "12.0.0-0",
                "12.0.0-1",
                "12.0.1-0",
                "12.1.0-0",
            ],
        ),
        (
            "10-8.1_10",
            [
                "10-8.1_11",
                "10-8.1_12",
                "10-8.2_0",
                "10-8.2_1",
                "10-8.3_0",
                "10-8.3_1",
                "10-9.0_0",
                "10-9.0_1",
                "10-9.1_0",
                "10-10.0_0",
                "10-10.0_1",
                "10-10.1_0",
                "11-0.0_0",
                "11-0.0_1",
                "11-0.1_0",
                "11-1.0_0",
                "12-0.0_0",
                "12-0.0_1",
                "12-0.1_0",
                "12-1.0_0",
            ],
        ),
        ("8.1p1", ["8.2p1", "8.3p1", "9.0p1", "9.1p1", "10.0p1", "10.1p1"]),
    ],
)
def test_next_version(in_ver, ver_test):
    next_vers = [v for v in next_version(in_ver)]
    print(next_vers)
    assert next_vers == ver_test, next_vers


@pytest.mark.parametrize(
    "in_ver, ver_test",
    [
        ("8.1", ["8.2", "8.3", "9.0", "9.1", "10.0", "10.1"]),
        (
            "8.1.5",
            [
                "8.1.6",
                "8.1.7",
                "8.2.0",
                "8.2.1",
                "8.3.0",
                "8.3.1",
                "9.0.0",
                "9.0.1",
                "9.1.0",
                "10.0.0",
                "10.0.1",
                "10.1.0",
            ],
        ),
        ("8_1", ["8_2", "8_3", "9_0", "9_1", "10_0", "10_1"]),
        (
            "8_1_5",
            [
                "8_1_6",
                "8_1_7",
                "8_2_0",
                "8_2_1",
                "8_3_0",
                "8_3_1",
                "9_0_0",
                "9_0_1",
                "9_1_0",
                "10_0_0",
                "10_0_1",
                "10_1_0",
            ],
        ),
        ("8-1", ["8-2", "8-3", "9-0", "9-1", "10-0", "10-1"]),
        (
            "8-1-5",
            [
                "8-1-6",
                "8-1-7",
                "8-2-0",
                "8-2-1",
                "8-3-0",
                "8-3-1",
                "9-0-0",
                "9-0-1",
                "9-1-0",
                "10-0-0",
                "10-0-1",
                "10-1-0",
            ],
        ),
        (
            "8.1-10",
            [
                "8.1-11",
                "8.1-12",
                "8.2-0",
                "8.2-1",
                "8.3-0",
                "8.3-1",
                "9.0-0",
                "9.0-1",
                "9.1-0",
                "10.0-0",
                "10.0-1",
                "10.1-0",
            ],
        ),
        (
            "8.1_10",
            [
                "8.1_11",
                "8.1_12",
                "8.2_0",
                "8.2_1",
                "8.3_0",
                "8.3_1",
                "9.0_0",
                "9.0_1",
                "9.1_0",
                "10.0_0",
                "10.0_1",
                "10.1_0",
            ],
        ),
        (
            "10.8.1-10",
            [
                "10.8.1-11",
                "10.8.1-12",
                "10.8.2-0",
                "10.8.2-1",
                "10.8.3-0",
                "10.8.3-1",
                "10.9.0-0",
                "10.9.0-1",
                "10.9.1-0",
                "10.10.0-0",
                "10.10.0-1",
                "10.10.1-0",
                "11.0.0-0",
                "11.0.0-1",
                "11.0.1-0",
                "11.1.0-0",
                "12.0.0-0",
                "12.0.0-1",
                "12.0.1-0",
                "12.1.0-0",
            ],
        ),
        (
            "10-8.1_10",
            [
                "10-8.1_11",
                "10-8.1_12",
                "10-8.2_0",
                "10-8.2_1",
                "10-8.3_0",
                "10-8.3_1",
                "10-9.0_0",
                "10-9.0_1",
                "10-9.1_0",
                "10-10.0_0",
                "10-10.0_1",
                "10-10.1_0",
                "11-0.0_0",
                "11-0.0_1",
                "11-0.1_0",
                "11-1.0_0",
                "12-0.0_0",
                "12-0.0_1",
                "12-0.1_0",
                "12-1.0_0",
            ],
        ),
        (
            "1.1.1a",
            [
                "1.1.1b",
                "1.1.1c",
                "1.1.2a",
                "1.1.2b",
                "1.1.3a",
                "1.1.3b",
                "1.2.0a",
                "1.2.0b",
                "1.2.1a",
                "1.3.0a",
                "1.3.0b",
                "1.3.1a",
                "2.0.0a",
                "2.0.0b",
                "2.0.1a",
                "2.1.0a",
                "3.0.0a",
                "3.0.0b",
                "3.0.1a",
                "3.1.0a",
            ],
        ),
        ("2020a", ["2020b", "2020c", "2021a", "2021b", "2022a", "2022b"]),
    ],
)
def test_next_version_openssl(in_ver, ver_test):
    next_vers = [v for v in next_version(in_ver, increment_alpha=True)]
    print(next_vers)
    assert next_vers == ver_test


sample_cutensor = """
{% set version = "1.5.0" %}
{% set patch_version = "3" %}

package:
  name: cutensor
  version: {{ version }}.{{ patch_version }}

source:
  url: https://developer.download.nvidia.com/compute/cutensor/redist/libcutensor/linux-x86_64/libcutensor-linux-x86_64-{{ version }}.{{ patch_version }}-archive.tar.xz     # [linux64]
  url: https://developer.download.nvidia.com/compute/cutensor/redist/libcutensor/linux-ppc64le/libcutensor-linux-ppc64le-{{ version }}.{{ patch_version }}-archive.tar.xz   # [ppc64le]
  url: https://developer.download.nvidia.com/compute/cutensor/redist/libcutensor/linux-sbsa/libcutensor-linux-sbsa-{{ version }}.{{ patch_version }}-archive.tar.xz         # [aarch64]
  url: https://developer.download.nvidia.com/compute/cutensor/redist/libcutensor/windows-x86_64/libcutensor-windows-x86_64-{{ version }}.{{ patch_version }}-archive.zip    # [win64]

  sha256: 4fdebe94f0ba3933a422cff3dd05a0ef7a18552ca274dd12564056993f55471d  # [linux64]
  sha256: ad736acc94e88673b04a3156d7d3a408937cac32d083acdfbd8435582cbe15db  # [ppc64le]
  sha256: 5b9ac479b1dadaf40464ff3076e45f2ec92581c07df1258a155b5bcd142f6090  # [aarch64]
  sha256: de76f7d92600dda87a14ac756e9d0b5733cbceb88bcd20b3935a82c99342e6cd  # [win64]

build:
  number: 2
  # cuTENSOR v1.3.1 supports CUDA 10.2, 11.0, and 11.1+
  skip: True  # [win32 or cuda_compiler_version not in ("10.2", "11.0", "11.1")]
  script_env:
    # for some reason /usr/local/cuda is not added to $PATH in ppc64le's docker image
    - CUDA_HOME  # [ppc64le or aarch64]
  script:
    - mkdir -p $PREFIX/include                                             # [linux]
    - mv include/* $PREFIX/include/                                        # [linux]
    - mkdir -p $PREFIX/lib                                                 # [linux]
    - mv lib/{{ cuda_compiler_version }}/*.so* $PREFIX/lib/                # [linux and cuda_compiler_version in ("10.2", "11.0")]
    - mv lib/11/*.so* $PREFIX/lib/                                         # [linux and cuda_compiler_version == "11.1"]
    - patchelf --add-needed libcudart.so $PREFIX/lib/libcutensor.so        # [ppc64le]

    - copy include\\cutensor.h %LIBRARY_INC%\\                             # [win64]
    - copy include\\cutensorMg.h %LIBRARY_INC%\\                           # [win64]
    - mkdir %LIBRARY_INC%\\cutensor                                        # [win64]
    - copy include\\cutensor\\types.h %LIBRARY_INC%\\cutensor              # [win64]
    - del lib\\{{ cuda_compiler_version }}\\*static*                       # [win64 and cuda_compiler_version in ("10.2", "11.0")]
    - copy lib\\{{ cuda_compiler_version }}\\*.dll %LIBRARY_BIN%\\         # [win64 and cuda_compiler_version in ("10.2", "11.0")]
    - copy lib\\{{ cuda_compiler_version }}\\*.lib %LIBRARY_LIB%\\         # [win64 and cuda_compiler_version in ("10.2", "11.0")]
    - del lib\\11\\*static*                                                # [win64 and cuda_compiler_version in ("11.1", )]
    - copy lib\\11\\*.dll %LIBRARY_BIN%\\                                  # [win64 and cuda_compiler_version in ("11.1", )]
    - copy lib\\11\\*.lib %LIBRARY_LIB%\\                                  # [win64 and cuda_compiler_version in ("11.1", )]
  ignore_run_exports:
    - cudatoolkit
  run_exports:
    - {{ pin_subpackage('cutensor') }}
  missing_dso_whitelist:
    # suppress warning, as these are included in the run dependency
    - '*/libcublasLt.so*'  # [linux and cuda_compiler_version in ("11.0", "11.1")]
    - '*/cublasLt64*.dll'  # [win64 and cuda_compiler_version in ("11.0", "11.1")]

requirements:
  build:
    - {{ compiler('c') }}
    - {{ compiler('cuda') }}
    - sysroot_linux-64 2.17  # [linux64]
  host:
    - patchelf >=0.12  # [linux]
  run:
    - cudatoolkit {{ cuda_compiler_version }}  # [cuda_compiler_version in ("10.2", "11.0")]
    - cudatoolkit >=11.1,<12                   # [cuda_compiler_version == "11.1"]
  run_constrained:
    # Only GLIBC_2.17 or older symbols present
    - __glibc >=2.17      # [linux]

test:
  requires:
    - git
    - {{ compiler('c') }}
    - {{ compiler('cxx') }}
    - {{ compiler('cuda') }}
    - sysroot_linux-64 2.17  # [linux]
    # make sure we pick up the version matching the docker,
    # or the linker would complain
    - cudatoolkit {{ cuda_compiler_version }}
  files:
    - test_load_elf.c        # [linux]

about:
  home: https://developer.nvidia.com/cutensor
  license: LicenseRef-cuTENSOR-Software-License-Agreement
  license_url: https://docs.nvidia.com/cuda/cutensor/license.html
  license_file: LICENSE
  summary: "Tensor Linear Algebra on NVIDIA GPUs"
  description: |
    The cuTENSOR Library is a first-of-its-kind GPU-accelerated tensor linear
    algebra library providing tensor contraction, reduction and elementwise
    operations. cuTENSOR is used to accelerate applications in the areas of
    deep learning training and inference, computer vision, quantum chemistry
    and computational physics.
    License Agreements:- The packages are governed by the NVIDIA cuTENSOR
    Software License Agreement (EULA). By downloading and using the packages,
    you accept the terms and conditions of the NVIDIA cuTENSOR EULA -
    https://docs.nvidia.com/cuda/cutensor/license.html
  doc_url: https://docs.nvidia.com/cuda/cutensor/index.html
  dev_url: https://developer.nvidia.com/cutensor/downloads

extra:
  recipe-maintainers:
    - leofang
    - jakirkham
    - mtjrider
"""  # noqa


latest_url_nvidia_test_list = [
    (
        "cutensor",
        sample_cutensor,
        "1.4.0.3",
        "1.5.0.3",
        NVIDIA(),
        {},
    ),
]


@pytest.mark.parametrize(
    "name, inp, curr_ver, ver, source, urls",
    latest_url_nvidia_test_list,
)
def test_latest_version_nvidia(name, inp, curr_ver, ver, source, urls, tmpdir):
    pmy = LazyJson(os.path.join(tmpdir, "cf-scripts-test.json"))
    with pmy as _pmy:
        _pmy.update(parse_meta_yaml(inp)["source"])
        _pmy.update(
            {
                "feedstock_name": name,
                "version": curr_ver,
                "raw_meta_yaml": inp,
                "meta_yaml": parse_meta_yaml(inp),
            },
        )
    attempt = get_latest_version(name, pmy, [source])
    if ver is None:
        assert attempt["new_version"] is not False
        assert attempt["new_version"] != curr_ver
        assert VersionOrder(attempt["new_version"]) > VersionOrder(curr_ver)
    elif ver is False:
        assert attempt["new_version"] is ver
    else:
        assert ver == attempt["new_version"]


def test_latest_version_aws_sdk_cpp(tmpdir):
    name = "aws_sdk_cpp"
    with open(os.path.join(YAML_PATH, "version_%s.yaml" % name)) as fp:
        inp = fp.read()

    pmy = LazyJson(os.path.join(tmpdir, name + ".json"))
    with pmy as _pmy:
        _pmy.update(parse_meta_yaml(inp)["source"])
        _pmy.update(
            {
                "feedstock_name": name,
                "version": "1.11.68",
                "raw_meta_yaml": inp,
                "meta_yaml": parse_meta_yaml(inp),
            },
        )
    attempt = get_latest_version(name, pmy, [PyPI(), Github(), RawURL()])
    assert attempt["new_version"] is not None
    assert attempt["new_version"]
    print(attempt)


@pytest.mark.parametrize("n_jobs", [1, 2, 4, 8])
def test_filter_nodes_for_job(n_jobs: int):
    # instead of relying on the hash function, we check that a "random" sample is partitioned
    # into the correct number of jobs of roughly equal size

    all_nodes = [(f"node-{i}", {"payload": f"payload-{i}"}) for i in range(2048)]

    filtered_nodes = [
        list(filter_nodes_for_job(all_nodes, i, n_jobs)) for i in range(1, n_jobs + 1)
    ]

    # sum of job sizes should be equal to total number of nodes
    assert sum(len(nodes) for nodes in filtered_nodes) == len(all_nodes)

    # jobs should be disjoint
    frozen_nodes = [
        [(name, frozenset(attrs.items())) for (name, attrs) in job_nodes]
        for job_nodes in filtered_nodes
    ]
    assert len(set().union(*frozen_nodes)) == len(all_nodes)

    # jobs should have roughly equal size
    assert all(
        0.8 < n_jobs * len(nodes) / len(all_nodes) < 1.2 for nodes in filtered_nodes
    )


def test_include_node_parsing_error(caplog):
    package_name = "testpackage"
    payload_attrs = {"parsing_error": "She sells seashells by the seashore."}

    caplog.set_level(logging.DEBUG)
    assert not include_node(package_name, payload_attrs)

    assert f"Skipping {package_name}" in caplog.text
    assert "parsing error" in caplog.text
    assert "She sells seashells by the seashore." in caplog.text


def test_include_node_no_payload():
    package_name = "testpackage"
    payload_attrs = {}

    assert include_node(package_name, payload_attrs)


def test_include_node_archived(caplog):
    package_name = "testpackage"
    payload_attrs = {"archived": True}

    caplog.set_level(logging.DEBUG)
    assert not include_node(package_name, payload_attrs)

    assert f"Skipping {package_name}" in caplog.text
    assert "archived" in caplog.text


def test_include_node_archived_false(caplog):
    package_name = "testpackage"
    payload_attrs = {"archived": False}

    assert include_node(package_name, payload_attrs)


def test_include_node_bad_pull_request(caplog):
    package_name = "testpackage"
    payload_attrs = {"pr_info": {"bad": "Lorem Ipsum"}}

    caplog.set_level(logging.DEBUG)
    assert not include_node(package_name, payload_attrs)

    assert f"Skipping {package_name}" in caplog.text
    assert "Pull Request" in caplog.text
    assert "bad" in caplog.text
    assert "Lorem Ipsum" in caplog.text


def test_include_node_bad_pull_request_upstream(caplog):
    package_name = "testpackage"
    payload_attrs = {"pr_info": {"bad": "Upstream: Could not fetch URL"}}

    caplog.set_level(logging.DEBUG)
    # the node is included!
    assert include_node(package_name, payload_attrs)

    assert f"Note: {package_name}" in caplog.text
    assert "Pull Request" in caplog.text
    assert "bad" in caplog.text
    assert "upstream" in caplog.text
