import os
import pathlib
import shutil
import pprint
import subprocess
from flaky import flaky
from textwrap import dedent

import pytest

from conda_forge_tick.mamba_solver import (
    is_recipe_solvable,
    _norm_spec,
    FakeRepoData,
    FakePackage,
    MambaSolver,
    virtual_package_repodata,
    apply_pins,
    _mamba_factory,
)

FEEDSTOCK_DIR = os.path.join(os.path.dirname(__file__), "test_feedstock")


@flaky
def test_mamba_solver_apply_pins(tmp_path):
    with open(tmp_path / "meta.yaml", "w") as fp:
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
    - jpeg
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

    with open(tmp_path / "conda_build_config.yaml", "w") as fp:
        fp.write(
            """\
pin_run_as_build:
  python:
    min_pin: x.x
    max_pin: x.x
python:
- 3.8.* *_cpython
""",
        )
    import conda_build.api

    config = conda_build.config.get_or_merge_config(
        None,
        platform="linux",
        arch="64",
        variant_config_files=[],
    )
    cbc, _ = conda_build.variants.get_package_combined_spec(
        str(tmp_path),
        config=config,
    )

    solver = _mamba_factory(("conda-forge", "defaults"), "linux-64")

    metas = conda_build.api.render(
        str(tmp_path),
        platform="linux",
        arch="64",
        ignore_system_variants=True,
        variants=cbc,
        permit_undefined_jinja=True,
        finalize=False,
        bypass_env_check=True,
        channel_urls=("conda-forge", "defaults"),
    )

    m = metas[0][0]
    outnames = [m.name() for m, _, _ in metas]
    build_req = m.get_value("requirements/build", [])
    host_req = m.get_value("requirements/host", [])
    run_req = m.get_value("requirements/run", [])
    _, _, build_req, rx = solver.solve(build_req, get_run_exports=True)
    print("build req: %s" % pprint.pformat(build_req))
    print("build rex: %s" % pprint.pformat(rx))
    host_req = list(set(host_req) | rx["strong"])
    run_req = list(set(run_req) | rx["strong"])
    _, _, host_req, rx = solver.solve(host_req, get_run_exports=True)
    print("host req: %s" % pprint.pformat(host_req))
    print("host rex: %s" % pprint.pformat(rx))
    run_req = list(set(run_req) | rx["weak"])
    run_req = apply_pins(run_req, host_req, build_req, outnames, m)
    print("run req: %s" % pprint.pformat(run_req))
    assert any(r.startswith("python >=3.8") for r in run_req)
    assert any(r.startswith("jpeg >=9d") for r in run_req)


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


@flaky
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


@pytest.mark.xfail()
@flaky
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
    - galsim

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
    # we don't have galsim for this variant so this is an expected failure
    assert not solvable_by_variant["linux_aarch64_python3.6.____cpython"]
    assert not solvable_by_variant["linux_ppc64le_python3.6.____cpython"]
    # But we do have this one
    assert solvable_by_variant["linux_python3.7.____cpython"]


def test_r_base_cross_solvable():
    feedstock_dir = os.path.join(os.path.dirname(__file__), "r-base-feedstock")
    solvable, errors, _ = is_recipe_solvable(feedstock_dir)
    assert not solvable, pprint.pformat(errors)

    solvable, errors, _ = is_recipe_solvable(
        feedstock_dir,
        build_platform={"osx_arm64": "osx_64"},
    )
    assert solvable, pprint.pformat(errors)


def clone_and_checkout_repo(base_path: pathlib.Path, origin_url: str, ref: str):
    subprocess.run(
        f"cd {base_path} && git clone --depth=1 {origin_url} repo",
        shell=True,
    )
    return str(base_path / "repo")


@flaky
def test_arrow_solvable(tmp_path):
    feedstock_dir = clone_and_checkout_repo(
        tmp_path,
        "https://github.com/conda-forge/arrow-cpp-feedstock",
        ref="master",
    )
    solvable, errors, solvable_by_variant = is_recipe_solvable(feedstock_dir)
    pprint.pprint(solvable_by_variant)
    assert solvable


@pytest.mark.xfail()
@flaky
def test_guiqwt_solvable(tmp_path):
    """test for run exports as a single string in pyqt"""
    feedstock_dir = clone_and_checkout_repo(
        tmp_path,
        "https://github.com/conda-forge/guiqwt-feedstock",
        ref="master",
    )
    solvable, errors, solvable_by_variant = is_recipe_solvable(feedstock_dir)
    pprint.pprint(solvable_by_variant)
    assert solvable


@pytest.mark.xfail()
def test_datalad_solvable(tmp_path):
    """has an odd thing where it hangs"""
    feedstock_dir = clone_and_checkout_repo(
        tmp_path,
        "https://github.com/conda-forge/datalad-feedstock",
        ref="master",
    )
    solvable, errors, solvable_by_variant = is_recipe_solvable(feedstock_dir)
    pprint.pprint(solvable_by_variant)
    assert solvable


@flaky
def test_grpcio_solvable(tmp_path):
    """grpcio has a runtime dep on openssl which has strange pinning things in it"""
    feedstock_dir = clone_and_checkout_repo(
        tmp_path,
        "https://github.com/conda-forge/grpcio-feedstock",
        ref="master",
    )
    solvable, errors, solvable_by_variant = is_recipe_solvable(feedstock_dir)
    pprint.pprint(solvable_by_variant)
    assert solvable


@pytest.mark.xfail()
def test_cupy_solvable(tmp_path):
    """grpcio has a runtime dep on openssl which has strange pinning things in it"""
    feedstock_dir = clone_and_checkout_repo(
        tmp_path,
        "https://github.com/conda-forge/cupy-feedstock",
        ref="master",
    )
    solvable, errors, solvable_by_variant = is_recipe_solvable(feedstock_dir)
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


@flaky
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


def test_mamba_solver_hangs():
    solver = _mamba_factory(("conda-forge", "defaults"), "osx-64")
    res = solver.solve(
        [
            "pytest",
            "selenium",
            "requests-mock",
            "ncurses >=6.2,<7.0a0",
            "libffi >=3.2.1,<4.0a0",
            "xz >=5.2.5,<6.0a0",
            "nbconvert >=5.6",
            "sqlalchemy",
            "jsonschema",
            "six >=1.11",
            "python_abi 3.9.* *_cp39",
            "tornado",
            "jupyter",
            "requests",
            "jupyter_client",
            "notebook >=4.2",
            "tk >=8.6.10,<8.7.0a0",
            "openssl >=1.1.1h,<1.1.2a",
            "readline >=8.0,<9.0a0",
            "fuzzywuzzy",
            "python >=3.9,<3.10.0a0",
            "traitlets",
            "sqlite >=3.33.0,<4.0a0",
            "alembic",
            "zlib >=1.2.11,<1.3.0a0",
            "python-dateutil",
            "nbformat",
            "jupyter_core",
        ],
    )
    assert res[0]

    solver = _mamba_factory(("conda-forge", "defaults"), "linux-64")
    solver.solve(
        [
            "gdal >=2.1.0",
            "ncurses >=6.2,<7.0a0",
            "geopandas",
            "scikit-image >=0.16.0",
            "pandas",
            "pyproj >=2.2.0",
            "libffi >=3.2.1,<4.0a0",
            "six",
            "tk >=8.6.10,<8.7.0a0",
            "spectral",
            "zlib >=1.2.11,<1.3.0a0",
            "shapely",
            "readline >=8.0,<9.0a0",
            "python >=3.8,<3.9.0a0",
            "numpy",
            "python_abi 3.8.* *_cp38",
            "xz >=5.2.5,<6.0a0",
            "openssl >=1.1.1h,<1.1.2a",
            "sqlite >=3.33.0,<4.0a0",
        ],
    )
    assert res[0]


def test_arrow_solvable_timeout(tmp_path):
    feedstock_dir = clone_and_checkout_repo(
        tmp_path,
        "https://github.com/conda-forge/arrow-cpp-feedstock",
        ref="master",
    )
    # let's run this over and over again to make sure nothing weird is happening
    # with the killed processes
    for _ in range(6):
        solvable, errors, solvable_by_variant = is_recipe_solvable(
            feedstock_dir,
            timeout=10,
        )
        assert solvable
        assert errors == []
        assert solvable_by_variant == {}
