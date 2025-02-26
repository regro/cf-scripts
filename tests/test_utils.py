import contextlib
import textwrap
from io import StringIO
from unittest import mock
from unittest.mock import MagicMock, mock_open

import pytest

from conda_forge_tick.utils import (
    DEFAULT_GRAPH_FILENAME,
    _munge_dict_repr,
    extract_section_from_yaml_text,
    get_keys_default,
    load_existing_graph,
    load_graph,
    parse_munged_run_export,
    run_command_hiding_token,
    split_yaml_list_value_and_comment,
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


@pytest.mark.parametrize(
    "meta_yaml,section_name,result,exclude_requirements",
    [
        (
            textwrap.dedent(
                """
            package:
              name: foo
              version: 1.0.0
            build:
              number: 1
              string: h1234_0
            requirements:
              host:
                - python 3.8
                - numpy
              run:
                - python 3.8
                - numpy
            """
            ),
            "host",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        host:
                          - python 3.8
                          - numpy
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "  ",
                ),
            ],
            False,
        ),
        (
            textwrap.dedent(
                """
                host:
                  - python 3.8
                  - numpy
                """
            ),
            "host",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        host:
                          - python 3.8
                          - numpy
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "",
                ),
            ],
            False,
        ),
        (
            textwrap.dedent(
                """
            package:
              name: foo
              version: 1.0.0
            build:
              number: 1
              string: h1234_0
            requirements:
              host:
              - python 3.8
              - numpy
              run:
                - python 3.8
                - numpy
            """
            ),
            "host",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        host:
                          - python 3.8
                          - numpy
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "  ",
                ),
            ],
            False,
        ),
        (
            textwrap.dedent(
                """
            package:
              name: foo
              version: 1.0.0
            build:
              number: 1
              string: h1234_0
            requirements:
              host:
                - python 3.8
                - numpy
              run:
                - python 3.8
                - numpy
            """
            ),
            "build",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        build:
                          number: 1
                          string: h1234_0
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "",
                ),
            ],
            False,
        ),
        (
            textwrap.dedent(
                """
            package:
              name: foo
              version: 1.0.0
            build:
              number: 1
              string: h1234_0
            requirements:
              build:
                - blah
              host:
                - python 3.8
                - numpy
              run:
                - python 3.8
                - numpy
            """
            ),
            "build",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        build:
                          number: 1
                          string: h1234_0
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "",
                ),
            ],
            True,
        ),
        (
            textwrap.dedent(
                """
            package:
              name: foo
              version: 1.0.0
            build:
              number: 1
              string: h1234_0
            requirements:
              build:
                - blah
              host:
                - python 3.8
                - numpy
              run:
                - python 3.8
                - numpy
            """
            ),
            "build",
            [
                textwrap.indent(
                    textwrap.dedent(
                        """
                        build:
                          number: 1
                          string: h1234_0
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "",
                ),
                textwrap.indent(
                    textwrap.dedent(
                        """
                        build:
                          - blah
                        """
                    )[1:-1],
                    # ^ remove newlines at start and end from dedented string
                    # since dedent normalizes only-whitespace lines to newlines
                    "  ",
                ),
            ],
            False,
        ),
    ],
)
def test_extract_section_from_yaml_text(
    meta_yaml, section_name, result, exclude_requirements
):
    extracted_sections = extract_section_from_yaml_text(
        meta_yaml, section_name, exclude_requirements=exclude_requirements
    )
    assert extracted_sections == result


@pytest.mark.parametrize(
    "line,val,comment",
    [
        (
            "- python 3.8",
            "python 3.8",
            "",
        ),
        (
            "- python 3.8 # comment",
            "python 3.8",
            "# comment",
        ),
        (
            "- 'python# 3.8' # comment",
            "python 3.8",
            "# comment",
        ),
        (
            '- "python 3.8#" # comment',
            "python 3.8",
            "# comment",
        ),
    ],
)
def test_split_yaml_list_value_and_comment(line, val, comment):
    val, comment = split_yaml_list_value_and_comment(line)
    assert val == val
    assert comment == comment
