import os
import tempfile
import textwrap

import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import NoarchPythonMinCleanup, Version
from conda_forge_tick.migrators.noarch_python_min import _apply_noarch_python_min
from conda_forge_tick.utils import yaml_safe_load

TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")

VERSION_WITH_NOARCHPY = Version(
    set(),
    piggy_back_migrations=[NoarchPythonMinCleanup()],
)


@pytest.mark.parametrize(
    "feedstock,new_ver",
    [
        ("seaborn", "0.13.2"),
    ],
)
def test_noarch_python_min_minimigrator(feedstock, new_ver, tmpdir):
    before = f"noarch_python_min_{feedstock}_before_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, before)) as fp:
        in_yaml = fp.read()

    after = f"noarch_python_min_{feedstock}_after_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, after)) as fp:
        out_yaml = fp.read()

    recipe_dir = os.path.join(tmpdir, f"{feedstock}-feedstock")
    os.makedirs(recipe_dir, exist_ok=True)

    run_test_migration(
        m=VERSION_WITH_NOARCHPY,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": VERSION_WITH_NOARCHPY.migrator_version,
            "version": new_ver,
        },
        tmpdir=recipe_dir,
        should_filter=False,
    )


@pytest.mark.parametrize(
    "meta_yaml,expected_meta_yaml,preserve_existing_specs",
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
            False,
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
            False,
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
            True,
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
            False,
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

                test:
                  requires:
                    - python
                    - numpy
                """
            ),
            True,
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
            False,
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
            False,
        ),
    ],
)
def test_apply_noarch_python_min(
    meta_yaml, expected_meta_yaml, preserve_existing_specs
):
    with tempfile.TemporaryDirectory() as recipe_dir:
        mypth = os.path.join(recipe_dir, "meta.yaml")
        with open(mypth, "w") as f:
            f.write(meta_yaml)

        with open(mypth) as f:
            myaml = yaml_safe_load(f)
        attrs = {"meta_yaml": myaml}

        _apply_noarch_python_min(
            recipe_dir, attrs, preserve_existing_specs=preserve_existing_specs
        )

        with open(mypth) as f:
            assert f.read() == expected_meta_yaml
