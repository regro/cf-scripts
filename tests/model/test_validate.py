from pathlib import Path

import pytest
from pydantic import ValidationError

from conda_forge_tick.models.node_attributes import NodeAttributes

# TODO: CI execution

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
