import os

from conda_forge_tick.migrators import (JS, Version)


sample_js = '''{% set name = "jstz" %}
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
    - sannykr'''


sample_js2 = '''{% set name = "jstz" %}
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
'''


correct_js = '''{% set name = "jstz" %}
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
'''

multi_source = '''{% set version = "2.4.0" %}
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
'''

correct_multi_source = '''{% set version = "2.4.1" %}
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
'''

def test_js_migration(tmpdir):
    with open(os.path.join(tmpdir, 'meta.yaml'), 'w') as f:
        f.write(sample_js)
    js = JS()
    js.migrate(tmpdir, {})
    with open(os.path.join(tmpdir, 'meta.yaml'), 'r') as f:
        assert f.read() == correct_js


def test_js_migration2(tmpdir):
    with open(os.path.join(tmpdir, 'meta.yaml'), 'w') as f:
        f.write(sample_js2)
    js = JS()
    js.migrate(tmpdir, {})
    with open(os.path.join(tmpdir, 'meta.yaml'), 'r') as f:
        assert f.read() == correct_js


def test_version_migration(tmpdir):
    # Test meta.yaml with separate url for each platform
    with open(os.path.join(tmpdir, 'meta.yaml'), 'w') as f:
        f.write(multi_source)
    v = Version()
    v.migrate(tmpdir, {'new_version': '2.4.1'})
    with open(os.path.join(tmpdir, 'meta.yaml'), 'r') as f:
        assert f.read() == correct_multi_source
