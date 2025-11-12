from pathlib import Path

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import (
    Build2HostMigrator,
    CrossCompilationForARMAndPower,
    CrossPythonMigrator,
    CrossRBaseMigrator,
    GuardTestingMigrator,
    GuardTestingWinMigrator,
    NoCondaInspectMigrator,
    UpdateCMakeArgsMigrator,
    UpdateCMakeArgsWinMigrator,
    UpdateConfigSubGuessMigrator,
    Version,
)

YAML_PATHS = [
    Path(__file__).parent / "test_yaml/cross_compile",
    Path(__file__).parent / "test_v1_yaml/cross_compile",
]
YAML_PATH = YAML_PATHS[0]

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}

config_migrator = UpdateConfigSubGuessMigrator()
guard_testing_migrator = GuardTestingMigrator()
guard_testing_win_migrator = GuardTestingWinMigrator()
cmake_migrator = UpdateCMakeArgsMigrator()
cmake_win_migrator = UpdateCMakeArgsWinMigrator()
cross_python_migrator = CrossPythonMigrator()
cross_rbase_migrator = CrossRBaseMigrator()
b2h_migrator = Build2HostMigrator()
nci_migrator = NoCondaInspectMigrator()
arm_and_power_migrator = CrossCompilationForARMAndPower()

version_migrator_autoconf = Version(
    set(),
    piggy_back_migrations=[
        config_migrator,
        cmake_migrator,
        cmake_win_migrator,
        guard_testing_migrator,
        guard_testing_win_migrator,
    ],
    total_graph=TOTAL_GRAPH,
)
version_migrator_cmake = Version(
    set(),
    piggy_back_migrations=[
        cmake_migrator,
        cmake_win_migrator,
        guard_testing_migrator,
        guard_testing_win_migrator,
        cross_rbase_migrator,
        cross_python_migrator,
    ],
    total_graph=TOTAL_GRAPH,
)
version_migrator_python = Version(
    set(),
    piggy_back_migrations=[cross_python_migrator],
    total_graph=TOTAL_GRAPH,
)
version_migrator_rbase = Version(
    set(),
    piggy_back_migrations=[cross_rbase_migrator],
    total_graph=TOTAL_GRAPH,
)
version_migrator_b2h = Version(
    set(),
    piggy_back_migrations=[b2h_migrator],
    total_graph=TOTAL_GRAPH,
)
version_migrator_nci = Version(
    set(),
    piggy_back_migrations=[nci_migrator],
    total_graph=TOTAL_GRAPH,
)
version_migrator_arm_and_power = Version(
    set(),
    piggy_back_migrations=[arm_and_power_migrator],
    total_graph=TOTAL_GRAPH,
)


def test_correct_config_sub(tmp_path):
    tmp_path.joinpath("recipe").mkdir()
    with open(tmp_path / "recipe/build.sh", "w") as f:
        f.write("#!/bin/bash\n./configure")
    run_test_migration(
        m=version_migrator_autoconf,
        inp=YAML_PATH.joinpath("config_recipe.yaml").read_text(),
        output=YAML_PATH.joinpath("config_recipe_correct.yaml").read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "4.5.0"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "4.5.0",
        },
        tmp_path=tmp_path,
    )
    with open(tmp_path / "recipe/build.sh") as f:
        assert len(f.readlines()) == 4


def test_make_check(tmp_path):
    tmp_path.joinpath("recipe").mkdir()
    with open(tmp_path / "recipe/build.sh", "w") as f:
        f.write("#!/bin/bash\nmake check")
    run_test_migration(
        m=version_migrator_autoconf,
        inp=YAML_PATH.joinpath("config_recipe.yaml").read_text(),
        output=YAML_PATH.joinpath("config_recipe_correct_make_check.yaml").read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "4.5.0"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "4.5.0",
        },
        tmp_path=tmp_path,
    )
    expected = [
        "#!/bin/bash\n",
        "# Get an updated config.sub and config.guess\n",
        "cp $BUILD_PREFIX/share/gnuconfig/config.* ./config\n",
        'if [[ "${CONDA_BUILD_CROSS_COMPILATION:-}" != "1" || "${CROSSCOMPILING_EMULATOR:-}" != "" ]]; then\n',
        "make check\n",
        "fi\n",
    ]
    with open(tmp_path / "recipe/build.sh") as f:
        lines = f.readlines()
        assert lines == expected


def test_cmake(tmp_path):
    tmp_path.joinpath("recipe").mkdir()
    with open(tmp_path / "recipe/build.sh", "w") as f:
        f.write("#!/bin/bash\ncmake ..\nctest")
    with open(tmp_path / "recipe/bld.bat", "w") as f:
        f.write("cmake ..\nctest")
    run_test_migration(
        m=version_migrator_cmake,
        inp=YAML_PATH.joinpath("config_recipe.yaml").read_text(),
        output=YAML_PATH.joinpath("config_recipe_correct_cmake.yaml").read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "4.5.0"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "4.5.0",
        },
        tmp_path=tmp_path,
    )
    expected_unix = [
        "#!/bin/bash\n",
        "cmake ${CMAKE_ARGS} ..\n",
        'if [[ "${CONDA_BUILD_CROSS_COMPILATION:-}" != "1" || "${CROSSCOMPILING_EMULATOR:-}" != "" ]]; then\n',
        "ctest\n",
        "fi\n",
    ]
    expected_win = [
        "cmake %CMAKE_ARGS% ..\n",
        'if not "%CONDA_BUILD_SKIP_TESTS%"=="1" (\n',
        "ctest\n",
        ")\n",
    ]
    with open(tmp_path / "recipe/build.sh") as f:
        lines = f.readlines()
        assert lines == expected_unix
    with open(tmp_path / "recipe/bld.bat") as f:
        lines = f.readlines()
        assert lines == expected_win


@pytest.mark.parametrize("recipe_version", [0, 1])
def test_cross_rbase(tmp_path, recipe_version: int):
    run_test_migration(
        m=version_migrator_rbase,
        inp=YAML_PATHS[recipe_version].joinpath("rbase_recipe.yaml").read_text(),
        output=YAML_PATHS[recipe_version]
        .joinpath("rbase_recipe_correct.yaml")
        .read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "2.0.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "2.0.1",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )


@pytest.mark.parametrize("recipe_version", [0, 1])
def test_cross_rbase_build_sh(tmp_path, recipe_version: int):
    tmp_path.joinpath("recipe").mkdir()
    with open(tmp_path / "recipe/build.sh", "w") as f:
        f.write("#!/bin/bash\nR CMD INSTALL --build .")
    run_test_migration(
        m=version_migrator_rbase,
        inp=YAML_PATHS[recipe_version].joinpath("rbase_recipe.yaml").read_text(),
        output=YAML_PATHS[recipe_version]
        .joinpath("rbase_recipe_correct.yaml")
        .read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "2.0.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "2.0.1",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )
    expected = [
        "#!/bin/bash\n",
        "\n",
        "export DISABLE_AUTOBREW=1\n",
        "\n",
        "# shellcheck disable=SC2086\n",
        "${R} CMD INSTALL --build . ${R_ARGS}\n",
    ]
    with open(tmp_path / "recipe/build.sh") as f:
        lines = f.readlines()
        assert lines == expected


@pytest.mark.parametrize("recipe_version", [0, 1])
def test_cross_python(tmp_path, recipe_version: int):
    run_test_migration(
        m=version_migrator_python,
        inp=YAML_PATHS[recipe_version].joinpath("python_recipe.yaml").read_text(),
        output=YAML_PATHS[recipe_version]
        .joinpath("python_recipe_correct.yaml")
        .read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )


@pytest.mark.parametrize("recipe_version", [0, 1])
def test_cross_python_no_build(tmp_path, recipe_version: int):
    run_test_migration(
        m=version_migrator_python,
        inp=YAML_PATHS[recipe_version]
        .joinpath("python_no_build_recipe.yaml")
        .read_text(),
        output=YAML_PATHS[recipe_version]
        .joinpath("python_no_build_recipe_correct.yaml")
        .read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "2020.6.20"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "2020.6.20",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )


@pytest.mark.parametrize("recipe_version", [0, 1])
def test_build2host(recipe_version, tmp_path):
    run_test_migration(
        m=version_migrator_b2h,
        inp=YAML_PATHS[recipe_version].joinpath("python_recipe_b2h.yaml").read_text(),
        output=YAML_PATHS[recipe_version]
        .joinpath("python_recipe_b2h_correct.yaml")
        .read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )


@pytest.mark.parametrize("recipe_version", [0, 1])
def test_build2host_buildok(recipe_version, tmp_path):
    run_test_migration(
        m=version_migrator_b2h,
        inp=YAML_PATHS[recipe_version]
        .joinpath("python_recipe_b2h_buildok.yaml")
        .read_text(),
        output=YAML_PATHS[recipe_version]
        .joinpath("python_recipe_b2h_buildok_correct.yaml")
        .read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )


@pytest.mark.parametrize("recipe_version", [0, 1])
def test_build2host_bhskip(recipe_version, tmp_path):
    run_test_migration(
        m=version_migrator_b2h,
        inp=YAML_PATHS[recipe_version]
        .joinpath("python_recipe_b2h_bhskip.yaml")
        .read_text(),
        output=YAML_PATHS[recipe_version]
        .joinpath("python_recipe_b2h_bhskip_correct.yaml")
        .read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )


def test_nocondainspect(tmp_path):
    run_test_migration(
        m=version_migrator_nci,
        inp=YAML_PATH.joinpath("python_recipe_nci.yaml").read_text(),
        output=YAML_PATH.joinpath("python_recipe_nci_correct.yaml").read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmp_path=tmp_path,
    )


@pytest.mark.parametrize("build_sh", [False, True])
@pytest.mark.parametrize("recipe_version", [0, 1])
def test_cross_compilation_for_arm_and_power(
    tmp_path, build_sh: bool, recipe_version: int
):
    tmp_path.joinpath("conda-forge.yml").write_text(
        """\
build_platform:
  linux_64: linux_64
provider:
  linux_aarch64: default
  linux_ppc64le: default
"""
    )
    if build_sh:
        tmp_path.joinpath("recipe").mkdir()
        tmp_path.joinpath("recipe/build.sh").write_text(
            """\
#!/bin/bash

if [[ "$CONDA_BUILD_CROSS_COMPILATION" == "0" ]]; then
    make check
fi
"""
        )

    run_test_migration(
        m=version_migrator_arm_and_power,
        # this migrator does not change the recipe file, so any unchanged recipe is fine
        inp=YAML_PATHS[recipe_version]
        .joinpath("python_recipe_b2h_buildok.yaml")
        .read_text(),
        output=YAML_PATHS[recipe_version]
        .joinpath("python_recipe_b2h_buildok_correct.yaml")
        .read_text(),
        prb="Dependencies have been updated if changed",
        kwargs={"new_version": "1.19.1"},
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "1.19.1",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )

    assert (
        tmp_path.joinpath("conda-forge.yml").read_text()
        == """\
build_platform:
  linux_64: linux_64
  linux_aarch64: linux_64
  linux_ppc64le: linux_64
provider:
  linux_aarch64: default
  linux_ppc64le: default
"""
    )
    if build_sh:
        assert (
            tmp_path.joinpath("recipe/build.sh").read_text()
            == """\
#!/bin/bash

if [[ "${CONDA_BUILD_CROSS_COMPILATION:-}" != "1" || "${CROSSCOMPILING_EMULATOR}" != "" ]]; then
    make check
fi
"""
        )
