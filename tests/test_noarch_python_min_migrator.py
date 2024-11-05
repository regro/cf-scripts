import os
import tempfile
import textwrap

import pytest

from conda_forge_tick.migrators.noarch_python_min import _apply_noarch_python_min
from conda_forge_tick.utils import yaml_safe_load


@pytest.mark.parametrize(
    "meta_yaml,expected_meta_yaml,force_apply",
    [
        (
            textwrap.dedent(
                """\
                build:
                  noarch: python

                requirements:
                  host:
                    - python
                    - numpy
                  run:
                    - python
                    - numpy

                test:
                  requires:
                    - python
                    - numpy
                """
            ),
            textwrap.dedent(
                """\
                {% set python_min = python_min|default("0.1a0") %}

                build:
                  noarch: python

                requirements:
                  host:
                    - python {{ python_min }}.*
                    - numpy
                  run:
                    - python >={{ python_min }}
                    - numpy

                test:
                  requires:
                    - python ={{ python_min }}
                    - numpy
                """
            ),
            True,
        ),
        (
            textwrap.dedent(
                """\
                build:
                  noarch: python

                requirements:
                  host:
                    - python
                    - numpy
                  run:
                    - python
                    - numpy

                test:
                  imports:
                    - blah
                """
            ),
            textwrap.dedent(
                """\
                {% set python_min = python_min|default("0.1a0") %}

                build:
                  noarch: python

                requirements:
                  host:
                    - python {{ python_min }}.*
                    - numpy
                  run:
                    - python >={{ python_min }}
                    - numpy

                test:
                  requires:
                    - python ={{ python_min }}
                  imports:
                    - blah
                """
            ),
            True,
        ),
        (
            textwrap.dedent(
                """\
                build:
                  noarch: python

                requirements:
                  host:
                    - python 3.6.*
                    - numpy
                  run:
                    - python
                    - numpy

                test:
                  requires:
                    - python =3.6
                    - numpy
                """
            ),
            textwrap.dedent(
                """\
                {% set python_min = python_min|default("0.1a0") %}

                build:
                  noarch: python

                requirements:
                  host:
                    - python 3.6.*
                    - numpy
                  run:
                    - python >={{ python_min }}
                    - numpy

                test:
                  requires:
                    - python =3.6
                    - numpy
                """
            ),
            False,
        ),
        (
            textwrap.dedent(
                """\
                build:
                  noarch: python

                requirements:
                  host:
                    - python 3.6.*  # this is cool
                    - numpy
                  run:
                    - python
                    - numpy

                test:
                  requires:
                    - python =3.6
                    - numpy
                """
            ),
            textwrap.dedent(
                """\
                {% set python_min = python_min|default("0.1a0") %}

                build:
                  noarch: python

                requirements:
                  host:
                    - python {{ python_min }}.*  # this is cool
                    - numpy
                  run:
                    - python >={{ python_min }}
                    - numpy

                test:
                  requires:
                    - python ={{ python_min }}
                    - numpy
                """
            ),
            True,
        ),
    ],
)
def test_apply_noarch_python_min(meta_yaml, expected_meta_yaml, force_apply):
    with tempfile.TemporaryDirectory() as recipe_dir:
        mypth = os.path.join(recipe_dir, "meta.yaml")
        with open(mypth, "w") as f:
            f.write(meta_yaml)

        with open(mypth) as f:
            myaml = yaml_safe_load(f)
        attrs = {"meta_yaml": myaml}

        _apply_noarch_python_min(recipe_dir, attrs, force_apply=force_apply)

        with open(mypth) as f:
            assert f.read() == expected_meta_yaml
