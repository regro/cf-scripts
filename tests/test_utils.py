from unittest import mock
from unittest.mock import MagicMock, mock_open

import pytest

from conda_forge_tick.utils import (
    DEFAULT_GRAPH_FILENAME,
    get_keys_default,
    load_existing_graph,
    load_graph,
)

EMPTY_JSON = "{}"
DEMO_GRAPH = """
{
    "directed": true,
    "graph": {
        "outputs_lut": {
            "package1": {
                "__set__": true,
                "elements": [
                    "package1"
                ]
            },
            "package2": {
                "__set__": true,
                "elements": [
                    "package2"
                ]
            }
        }
    },
    "links": [
        {
            "source": "package1",
            "target": "package2"
        }
    ],
    "multigraph": false,
    "nodes": [
        {
            "id": "package1",
            "payload": {
                "__lazy_json__": "node_attrs/package1.json"
            }
        }
    ]
}
"""


def test_get_keys_default():
    attrs = {
        "conda-forge.yml": {
            "bot": {
                "version_updates": {
                    "sources": ["pypi"],
                },
            },
        },
    }
    assert get_keys_default(
        attrs,
        ["conda-forge.yml", "bot", "version_updates", "sources"],
        {},
        None,
    ) == ["pypi"]


def test_get_keys_default_none():
    attrs = {
        "conda-forge.yml": {
            "bot": None,
        },
    }
    assert (
        get_keys_default(
            attrs,
            ["conda-forge.yml", "bot", "check_solvable"],
            {},
            False,
        )
        is False
    )


def test_load_graph():
    with mock.patch("builtins.open", mock_open(read_data=DEMO_GRAPH)) as mock_file:
        gx = load_graph()

        assert gx is not None

        assert gx.nodes.keys() == {"package1", "package2"}

    mock_file: MagicMock
    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME)])


def test_load_graph_empty_graph():
    with mock.patch("builtins.open", mock_open(read_data=EMPTY_JSON)) as mock_file:
        gx = load_graph()

        assert gx is None

    mock_file: MagicMock
    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME)])


@mock.patch("os.path.exists")
def test_load_graph_file_does_not_exist(exists_mock: MagicMock):
    exists_mock.return_value = False

    with mock.patch("builtins.open", mock_open(read_data=EMPTY_JSON)) as mock_file:
        load_graph()

    mock_file: MagicMock
    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME, "w")])


def test_load_existing_graph():
    with mock.patch("builtins.open", mock_open(read_data=DEMO_GRAPH)) as mock_file:
        gx = load_existing_graph()

        assert gx.nodes.keys() == {"package1", "package2"}

    mock_file: MagicMock
    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME)])


def test_load_existing_graph_empty_graph():
    with mock.patch("builtins.open", mock_open(read_data=EMPTY_JSON)) as mock_file:
        with pytest.raises(ValueError, match="empty JSON"):
            load_existing_graph()

    mock_file: MagicMock
    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME)])


@mock.patch("os.path.exists")
def test_load_existing_graph_file_does_not_exist(exists_mock: MagicMock):
    exists_mock.return_value = False

    with mock.patch("builtins.open", mock_open(read_data=EMPTY_JSON)) as mock_file:
        with pytest.raises(ValueError, match="empty JSON"):
            load_existing_graph()

    mock_file: MagicMock
    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME, "w")])
