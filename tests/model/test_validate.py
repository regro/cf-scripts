from pathlib import Path

import pytest
from pydantic import ValidationError

from conda_forge_tick.models.node_attributes import NodeAttributes

"""
These tests validate that the node attributes files in the node_attrs directory are valid JSON and
conform to the NodeAttributes schema.

Since we currently do not use the NodeAttributes schema in production, and also do not enforce some rules
in the conda-smithy linter (e.g. valid URLs in , it is very possible that failures in these tests can occur.

The most likely cause of these failures is that the meta.yaml file of an upstream feedstock does not conform to
the MetaYaml schema - note that some fields of the NodeAttributes schema are derived directly from the meta.yaml file.

You can add the name of a feedstock to the KNOWN_BAD_FEEDSTOCKS list if you know that it will fail these tests.
After fixing the issue, you can remove the feedstock from the list.
"""

NODE_ATTRS_DIR = Path("node_attrs")

KNOWN_BAD_FEEDSTOCKS = [
    "gmatelastoplasticqpot3d",  # missing platforms
    "tqdm",  # invalid conda-forge.yaml build platform "win:azure"
    "semi-ate-stdf",  # missing platforms
    "thrust",  # missing platforms
    "make_arq",  # invalid conda-forge.yml build platform "windows"
    "cub",  # missing platforms
    "mamba",  # outdated version field in dependency graph (package.version field removed in meta.yaml)
    "napari",  # outdated version field in dependency graph (package.version field removed in meta.yaml)
    "birka",  # outdated version field in dependency graph (package.version field removed in meta.yaml)
    "xsimd",  # recipe/meta.yaml about.doc_url has a typo in the URL scheme
    "pytao",  # recipe/meta.yaml about.dev_url has a typo in the URL scheme
    "anyqt",  # recipe/meta.yaml about.dev_url has a typo in the URL scheme
    "cubed",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "condastats",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "pytermgui",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "torcpy",  # recipe/meta.yaml about.dev_url has typo
    "scikit-plot",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "wagtall-bakery",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "matbench-genmetrics",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "neutronics_material_maker",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "gulp",  # recipe/meta.yaml about.dev_url has invalid URL scheme
    "wagtail-bakery",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "mp_time_split",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "shippinglabel",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "cddlib",  # recipe/meta.yaml about.doc_url has "ftp" URL scheme (and is unreachable)
    "cf-autotick-bot-test-package",  # recipe/meta.yaml source.sha256 is invalid
    "vs2008_runtime",  # node attributes error: build.skip is true for non-Windows, but osx and linux are platforms
    "llspy",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "everett",  # recipe/meta.yaml about.dev_url has invalid URL scheme
    "scheil",  # recipe/meta.yaml about.doc_url is not a valid URL
    "llspy-slm",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "path.py",  # build.noarch: true in meta.yaml, which should probably be build.noarch: python
    "parallel-hashmap",  # build.noarch: true (should be generic) but also probably broken on Windows
]


def pytest_generate_tests(metafunc):
    if "node_file_valid" in metafunc.fixturenames:
        files = list(NODE_ATTRS_DIR.rglob("*.json"))
        files = [f for f in files if f.stem not in KNOWN_BAD_FEEDSTOCKS]
        metafunc.parametrize("node_file_valid", files, ids=lambda x: x.stem)

    if "node_file_invalid" in metafunc.fixturenames:
        files = list(NODE_ATTRS_DIR.rglob("*.json"))
        files = [f for f in files if f.stem in KNOWN_BAD_FEEDSTOCKS]
        metafunc.parametrize("node_file_invalid", files, ids=lambda x: x.stem)


def test_validate_node_attrs_valid(node_file_valid):
    with open(node_file_valid) as f:
        node_attrs = f.read()
    NodeAttributes.validate_json(node_attrs)


def test_validate_node_attrs_invalid(node_file_invalid):
    with open(node_file_invalid) as f:
        node_attrs = f.read()
    with pytest.raises(ValidationError):
        NodeAttributes.validate_json(node_attrs)
