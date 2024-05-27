import contextlib
from io import StringIO
from subprocess import CompletedProcess
from unittest import mock
from unittest.mock import MagicMock, mock_open

import pytest

from conda_forge_tick.utils import (
    DEFAULT_GRAPH_FILENAME,
    _munge_dict_repr,
    get_keys_default,
    load_existing_graph,
    load_graph,
    parse_munged_run_export,
    print_subprocess_output_strip_token,
    run_command_hiding_token,
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

    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME)])


def test_load_graph_empty_graph():
    with mock.patch("builtins.open", mock_open(read_data=EMPTY_JSON)) as mock_file:
        gx = load_graph()

        assert gx is None

    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME)])


@mock.patch("os.path.exists")
def test_load_graph_file_does_not_exist(exists_mock: MagicMock):
    exists_mock.return_value = False

    with mock.patch("builtins.open", mock_open(read_data=EMPTY_JSON)) as mock_file:
        load_graph()

    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME, "w")])


def test_load_existing_graph():
    with mock.patch("builtins.open", mock_open(read_data=DEMO_GRAPH)) as mock_file:
        gx = load_existing_graph()

        assert gx.nodes.keys() == {"package1", "package2"}

    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME)])


def test_load_existing_graph_empty_graph():
    with mock.patch("builtins.open", mock_open(read_data=EMPTY_JSON)) as mock_file:
        with pytest.raises(ValueError, match="empty JSON"):
            load_existing_graph()

    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME)])


@mock.patch("os.path.exists")
def test_load_existing_graph_file_does_not_exist(exists_mock: MagicMock):
    exists_mock.return_value = False

    with mock.patch("builtins.open", mock_open(read_data=EMPTY_JSON)) as mock_file:
        with pytest.raises(ValueError, match="empty JSON"):
            load_existing_graph()

    mock_file.assert_has_calls([mock.call(DEFAULT_GRAPH_FILENAME, "w")])


def test_munge_dict_repr():
    d = {"a": 1, "b": 2, "weak": [1, 2, 3], "strong": {"a": 1, "b": 2}}
    print(_munge_dict_repr(d))
    assert parse_munged_run_export(_munge_dict_repr(d)) == d


def test_print_subprocess_output_strip_token_all_none():
    stdout = StringIO()
    stderr = StringIO()

    p = CompletedProcess(args=[], returncode=0, stdout=None, stderr=None)

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        print_subprocess_output_strip_token(p, "TOKEN")

    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""


def test_print_subprocess_output_strip_token_stdout_only():
    stdout = StringIO()
    stderr = StringIO()

    p = CompletedProcess(args=[], returncode=0, stdout="stdout", stderr=None)

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        print_subprocess_output_strip_token(p, "TOKEN")

    assert stdout.getvalue() == "stdout"
    assert stderr.getvalue() == ""


def test_print_subprocess_output_strip_token_stderr_only():
    stdout = StringIO()
    stderr = StringIO()

    p = CompletedProcess(args=[], returncode=0, stdout=None, stderr="stderr")

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        print_subprocess_output_strip_token(p, "TOKEN")

    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "stderr"


def test_print_subprocess_output_strip_token_both():
    stdout = StringIO()
    stderr = StringIO()

    p = CompletedProcess(
        args=[], returncode=0, stdout="stdTOKEN.out", stderr="stdTOKEN.err"
    )

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        print_subprocess_output_strip_token(p, "TOKEN")

    assert stdout.getvalue() == "std*****.out"
    assert stderr.getvalue() == "std*****.err"


def test_print_subprocess_output_strip_token_no_token():
    stdout = StringIO()
    stderr = StringIO()

    p = CompletedProcess(args=[], returncode=0, stdout="stdout", stderr="stderr")

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        print_subprocess_output_strip_token(p, "TOKEN")

    assert stdout.getvalue() == "stdout"
    assert stderr.getvalue() == "stderr"


def test_print_subprocess_output_strip_token_multiple_occurrences():
    stdout = StringIO()
    stderr = StringIO()

    p = CompletedProcess(
        args=[], returncode=1, stdout="stdTOKEN-TOKEN.out", stderr="stdTOKEN-TOKEN.err"
    )

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        print_subprocess_output_strip_token(p, "TOKEN")

    assert stdout.getvalue() == "std*****-*****.out"
    assert stderr.getvalue() == "std*****-*****.err"


def test_print_subprocess_output_strip_token_bytes_in_stdout():
    stdout = StringIO()
    stderr = StringIO()

    p = CompletedProcess(
        args=[], returncode=1, stdout=b"stdTOKEN-TOKEN.out", stderr=b""
    )

    with pytest.raises(ValueError, match="Expected stdout and stderr to be str"):
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            print_subprocess_output_strip_token(p, "TOKEN")

    assert stdout.getvalue() == ""
    assert stderr.getvalue() == ""


def test_run_command_hiding_token():
    cmd = ["python", "-c", "print('stdTOKEN.out')"]

    stdout = StringIO()
    stderr = StringIO()

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        run_command_hiding_token(cmd, "TOKEN")

    assert stdout.getvalue() == "std*****.out\n"
    assert stderr.getvalue() == ""


def test_run_command_hiding_token_stderr():
    cmd = ["python", "-c", "import sys; sys.stderr.write('stdTOKEN.err')"]

    stdout = StringIO()
    stderr = StringIO()

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        run_command_hiding_token(cmd, "TOKEN")

    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "std*****.err"
