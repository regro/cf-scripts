import pytest

from conda_forge_tick.update_upstream_versions import (
    NPM, get_latest_version, next_version
)
from conda_forge_tick.utils import parse_meta_yaml, LazyJson

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
"""

latest_url_test_list = [
    (
        sample_npm,
        "3.1.1",
        NPM(),
        {"https://registry.npmjs.org/configurable-http-proxy": sample_npm_response},
    ),
]


@pytest.mark.parametrize("inp, ver, source, urls", latest_url_test_list)
def test_latest_version(inp, ver, source, urls, requests_mock, tmpdir):
    pmy = LazyJson(tmpdir.join("cf-scripts-test.json"))
    pmy.update(parse_meta_yaml(inp)["source"])
    [requests_mock.get(url, text=text) for url, text in urls.items()]
    assert ver == get_latest_version('configurable-http-proxy', pmy, [source])


@pytest.mark.parametrize('in_ver, ver_test', [
    ('8.1', ['8.2', '9.0']),
    ('8.1.5', ['8.1.6', '8.2.0', '9.0.0']),
    ('8_1', ['8_2', '9_0']),
    ('8_1_5', ['8_1_6', '8_2_0', '9_0_0']),
    ('8-1', ['8-2', '9-0']),
    ('8-1-5', ['8-1-6', '8-2-0', '9-0-0']),
    ('8.1-10', ['8.1-11', '8.2-0', '9.0-0']),
    ('8.1_10', ['8.1_11', '8.2_0', '9.0_0']),
    ('10.8.1-10', ['10.8.1-11', '10.8.2-0', '10.9.0-0', '11.0.0-0']),
    ('10-8.1_10', ['10-8.1_11', '10-8.2_0', '10-9.0_0', '11-0.0_0']),
    ('8.1p1', ['8.2p1', '9.0p1']),
])
def test_next_version(in_ver, ver_test):
    next_vers = [v for v in next_version(in_ver)]
    assert next_vers == ver_test
