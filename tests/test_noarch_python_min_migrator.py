import os
import tempfile
import textwrap

import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators.noarch_python_min import (
    NoarchPythonMinMigrator,
    _apply_noarch_python_min,
    _get_curr_python_min,
)
from conda_forge_tick.utils import yaml_safe_load

TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")

GLOBAL_PYTHON_MIN = _get_curr_python_min()
NEXT_GLOBAL_PYTHON_MIN = (
    GLOBAL_PYTHON_MIN.split(".")[0]
    + "."
    + str(int(GLOBAL_PYTHON_MIN.split(".")[1]) + 1)
)


@pytest.mark.parametrize(
    "meta_yaml,expected_meta_yaml",
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
                build:
                  noarch: python

                requirements:
                  host:
                    - python {{ python_min }}
                    - numpy
                  run:
                    - python >={{ python_min }}
                    - numpy

                test:
                  requires:
                    - python {{ python_min }}
                    - numpy
                """
            ),
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
                build:
                  noarch: python

                requirements:
                  host:
                    - python {{ python_min }}
                    - numpy
                  run:
                    - python >={{ python_min }}
                    - numpy

                test:
                  requires:
                    - python {{ python_min }}
                  imports:
                    - blah
                """
            ),
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
                build:
                  noarch: python

                requirements:
                  host:
                    - python {{ python_min }}  # this is cool
                    - numpy
                  run:
                    - python >={{ python_min }}
                    - numpy

                test:
                  requires:
                    - python {{ python_min }}
                    - numpy
                """
            ),
        ),
        (
            textwrap.dedent(
                f"""\
                build:
                  noarch: python

                requirements:
                  host:
                    - python >={NEXT_GLOBAL_PYTHON_MIN}  # this is cool
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
                f"""\
                {{% set python_min = '{NEXT_GLOBAL_PYTHON_MIN}' %}}
                build:
                  noarch: python

                requirements:
                  host:
                    - python {{{{ python_min }}}}  # this is cool
                    - numpy
                  run:
                    - python >={{{{ python_min }}}}
                    - numpy

                test:
                  requires:
                    - python {{{{ python_min }}}}
                    - numpy
                """
            ),
        ),
        (
            textwrap.dedent(
                f"""\
                build:
                  noarch: python

                requirements:
                  host:
                    - python >={GLOBAL_PYTHON_MIN}  # this is cool
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
                build:
                  noarch: python

                requirements:
                  host:
                    - python {{ python_min }}  # this is cool
                    - numpy
                  run:
                    - python >={{ python_min }}
                    - numpy

                test:
                  requires:
                    - python {{ python_min }}
                    - numpy
                """
            ),
        ),
        (
            textwrap.dedent(
                """\
                requirements:
                  host:
                    - python
                    - numpy
                  run:
                    - python
                    - numpy

                outputs:
                  - name: blah
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

                  - name: blah-2
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
                requirements:
                  host:
                    - python
                    - numpy
                  run:
                    - python
                    - numpy

                outputs:
                  - name: blah
                    build:
                      noarch: python
                    requirements:
                      host:
                        - python {{ python_min }}
                        - numpy
                      run:
                        - python >={{ python_min }}
                        - numpy
                    test:
                      requires:
                        - python {{ python_min }}
                      imports:
                        - blah

                  - name: blah-2
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

                outputs:
                  - name: blah
                    build:
                      number: 10
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

                  - name: blah-2
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
                build:
                  noarch: python

                requirements:
                  host:
                    - python {{ python_min }}
                    - numpy
                  run:
                    - python >={{ python_min }}
                    - numpy

                outputs:
                  - name: blah
                    build:
                      number: 10
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

                  - name: blah-2
                    requirements:
                      host:
                        - python {{ python_min }}
                        - numpy
                      run:
                        - python >={{ python_min }}
                        - numpy

                test:
                  requires:
                    - python {{ python_min }}
                    - numpy
                """
            ),
        ),
    ],
)
def test_apply_noarch_python_min(
    meta_yaml,
    expected_meta_yaml,
):
    with tempfile.TemporaryDirectory() as recipe_dir:
        mypth = os.path.join(recipe_dir, "meta.yaml")
        with open(mypth, "w") as f:
            f.write(meta_yaml)

        with open(mypth) as f:
            myaml = yaml_safe_load(f)
        attrs = {"meta_yaml": myaml}

        _apply_noarch_python_min(
            recipe_dir,
            attrs,
        )

        with open(mypth) as f:
            assert f.read() == expected_meta_yaml


def test_noarch_python_min_migrator(tmpdir):
    with open(
        os.path.join(TEST_YAML_PATH, "noarch_python_min_seaborn_before_meta.yaml")
    ) as f:
        recipe_before = f.read()
    with open(
        os.path.join(TEST_YAML_PATH, "noarch_python_min_seaborn_after_meta.yaml")
    ) as f:
        recipe_after = f.read()
    m = NoarchPythonMinMigrator()
    run_test_migration(
        m=m,
        inp=recipe_before,
        output=recipe_after,
        kwargs={},
        prb="This PR updates the recipe to use the `noarch: python`",
        mr_out={
            "migrator_name": "NoarchPythonMinMigrator",
            "migrator_version": m.migrator_version,
            "name": "noarch_python_min",
        },
        tmpdir=tmpdir,
    )
