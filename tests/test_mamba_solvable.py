import os
import pathlib
import shutil
from textwrap import dedent

import pytest

from conda_forge_tick.mamba_solver import (
    is_recipe_solvable,
    _norm_spec,
    FakeRepoData,
    FakePackage,
    MambaSolver,
    virtual_package_repodata,
)

FEEDSTOCK_DIR = os.path.join(os.path.dirname(__file__), "test_feedstock")


def test_mamba_solver_nvcc():
    virtual_packages = virtual_package_repodata()
    solver = MambaSolver([virtual_packages, "conda-forge", "defaults"], "linux-64")
    out = solver.solve(["gcc_linux-64 7.*", "gxx_linux-64 7.*", "nvcc_linux-64 11.0.*"])
    assert out[0], out[1]


@pytest.fixture()
def feedstock_dir(tmp_path):
    ci_support = tmp_path / ".ci_support"
    ci_support.mkdir(exist_ok=True)
    src_ci_support = pathlib.Path(FEEDSTOCK_DIR) / ".ci_support"
    for fn in os.listdir(src_ci_support):
        shutil.copy(src_ci_support / fn, ci_support / fn)
    return str(tmp_path)


def test_is_recipe_solvable_ok(feedstock_dir):
    recipe_file = os.path.join(feedstock_dir, "recipe", "meta.yaml")
    os.makedirs(os.path.dirname(recipe_file), exist_ok=True)
    with open(recipe_file, "w") as fp:
        fp.write(
            """\
{% set name = "cf-autotick-bot-test-package" %}
{% set version = "0.9" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  path: .

build:
  number: 8

requirements:
  host:
    - python
    - pip
  run:
    - python

test:
  commands:
    - echo "works!"

about:
  home: https://github.com/regro/cf-scripts
  license: BSD-3-Clause
  license_family: BSD
  license_file: LICENSE
  summary: testing feedstock for the regro-cf-autotick-bot

extra:
  recipe-maintainers:
    - beckermr
    - conda-forge/bot
""",
        )
    assert is_recipe_solvable(feedstock_dir)[0]


def test_unsolvable_for_particular_python(feedstock_dir):
    recipe_file = os.path.join(feedstock_dir, "recipe", "meta.yaml")
    os.makedirs(os.path.dirname(recipe_file), exist_ok=True)
    with open(recipe_file, "w") as fp:
        fp.write(
            """\
{% set name = "cf-autotick-bot-test-package" %}
{% set version = "0.9" %}

package:
    name: {{ name|lower }}
    version: {{ version }}

source:
    path: .

build:
    number: 8

requirements:
    host:
    - python
    - pip
    run:
    - python
    - asyncpg

test:
    commands:
    - echo "works!"

about:
    home: https://github.com/regro/cf-scripts
    license: BSD-3-Clause
    license_family: BSD
    license_file: LICENSE
    summary: testing feedstock for the regro-cf-autotick-bot

extra:
    recipe-maintainers:
    - beckermr
    - conda-forge/bot
""",
        )
    solvable, errors, solvable_by_variant = is_recipe_solvable(feedstock_dir)
    print(solvable_by_variant)
    assert not solvable
    # we don't have asyncpg for this variant so this is an expected failure
    assert not solvable_by_variant["linux_aarch64_python3.6.____cpython"]
    # But we do have this one
    assert solvable_by_variant["linux_ppc64le_python3.6.____cpython"]


def clone_and_checkout_repo(base_path: pathlib.Path, origin_url: str, ref: str):
    from conda_forge_tick.git_xonsh_utils import fetch_repo

    fetch_repo(
        feedstock_dir=str(base_path / "repo"),
        origin=origin_url,
        upstream=origin_url,
        branch=ref,
    )
    return str(base_path / "repo")


def test_arrow_solvable(tmp_path):
    feedstock_dir = clone_and_checkout_repo(
        tmp_path,
        "https://github.com/conda-forge/arrow-cpp-feedstock",
        ref="master",
    )
    solvable, errors, solvable_by_variant = is_recipe_solvable(feedstock_dir)
    print(solvable_by_variant)
    assert solvable


def test_grpcio_solvable(tmp_path):
    """grpcio has a runtime dep on openssl which has strange pinning things in it"""
    feedstock_dir = clone_and_checkout_repo(
        tmp_path,
        "https://github.com/conda-forge/grpcio-feedstock",
        ref="master",
    )
    solvable, errors, solvable_by_variant = is_recipe_solvable(feedstock_dir)
    import pprint

    pprint.pprint(solvable_by_variant)
    assert solvable


def test_cupy_solvable(tmp_path):
    """grpcio has a runtime dep on openssl which has strange pinning things in it"""
    feedstock_dir = clone_and_checkout_repo(
        tmp_path,
        "https://github.com/conda-forge/cupy-feedstock",
        ref="master",
    )
    solvable, errors, solvable_by_variant = is_recipe_solvable(feedstock_dir)
    import pprint

    pprint.pprint(solvable_by_variant)
    assert solvable


def test_is_recipe_solvable_notok(feedstock_dir):
    recipe_file = os.path.join(feedstock_dir, "recipe", "meta.yaml")
    os.makedirs(os.path.dirname(recipe_file), exist_ok=True)
    with open(recipe_file, "w") as fp:
        fp.write(
            """\
{% set name = "cf-autotick-bot-test-package" %}
{% set version = "0.9" %}

package:
  name: {{ name|lower }}
  version: {{ version }}

source:
  path: .

build:
  number: 8

requirements:
  host:
    - python >=4.0  # [osx]
    - python  # [not osx]
    - pip
  run:
    - python

test:
  commands:
    - echo "works!"

about:
  home: https://github.com/regro/cf-scripts
  license: BSD-3-Clause
  license_family: BSD
  license_file: LICENSE
  summary: testing feedstock for the regro-cf-autotick-bot

extra:
  recipe-maintainers:
    - beckermr
    - conda-forge/bot
""",
        )
    assert not is_recipe_solvable(feedstock_dir)[0]


@pytest.mark.parametrize(
    "inreq,outreq",
    [
        ("blah 1.1*", "blah 1.1.*"),
        ("blah * *_osx", "blah * *_osx"),
        ("blah 1.1", "blah 1.1.*"),
        ("blah =1.1", "blah 1.1.*"),
        ("blah * *_osx", "blah * *_osx"),
        ("blah 1.2 *_osx", "blah 1.2.* *_osx"),
        ("blah >=1.1", "blah >=1.1"),
        ("blah >=1.1|5|>=5,<10|19.0", "blah >=1.1|5.*|>=5,<10|19.0.*"),
        ("blah >=1.1|5| >=5 , <10 |19.0", "blah >=1.1|5.*|>=5,<10|19.0.*"),
    ],
)
def test_norm_spec(inreq, outreq):
    assert _norm_spec(inreq) == outreq


def test_virtual_package(feedstock_dir, tmp_path_factory):
    recipe_file = os.path.join(feedstock_dir, "recipe", "meta.yaml")
    os.makedirs(os.path.dirname(recipe_file), exist_ok=True)

    with FakeRepoData(tmp_path_factory.mktemp("channel")) as repodata:
        for pkg in [
            FakePackage("fakehostvirtualpkgdep", depends=frozenset(["__virtual >=10"])),
            FakePackage("__virtual", version="10"),
        ]:
            repodata.add_package(pkg)

    with open(recipe_file, "w") as fp:
        fp.write(
            dedent(
                """
    package:
      name: "cf-autotick-bot-test-package"
      version: "0.9"

    source:
      path: .

    build:
      number: 8

    requirements:
      host:
        - python
        - fakehostvirtualpkgdep
        - pip
      run:
        - python
    """,
            ),
        )

    solvable, err, solve_by_variant = is_recipe_solvable(
        feedstock_dir,
        additional_channels=[repodata.channel_url],
    )
    assert solvable
