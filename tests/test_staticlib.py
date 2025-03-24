import os
import shutil
import textwrap

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.feedstock_parser import populate_feedstock_attributes
from conda_forge_tick.migrators.staticlib import (
    StaticLibMigrator,
    _munge_hash_matchspec,
    any_static_libs_out_of_date,
    attempt_update_static_libs,
    get_latest_static_lib,
    is_abstract_static_lib_spec,
)

TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")
TEST_YAML_PATH_V1 = os.path.join(os.path.dirname(__file__), "test_v1_yaml")

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}


@pytest.mark.parametrize(
    "spec,res",
    [
        ("llvm-*", True),
        ("llvm 15.0.*", True),
        ("llvm 15.0", True),
        ("llvm 15.0.* blah_*", True),
        ("llvm 15.0.7.* blah_*_5", True),
        ("llvm 15.0.7 blah_*_5", False),
        ("llvm 15.0.7 *_5", False),
        ("llvm 15.0.7 blah_h4541_5", False),
    ],
)
def test_is_abstract_static_lib_spec(spec, res):
    assert is_abstract_static_lib_spec(spec) is res


def test_staticlib_get_latest_static_lib():
    rec = get_latest_static_lib("llvmdev", "osx-64")
    rec15 = get_latest_static_lib("llvmdev 15.*", "osx-64")
    assert rec.version.split(".")[0] > rec15.version.split(".")[0]

    rec15b4 = get_latest_static_lib("llvmdev 15.* *_4", "osx-64")
    rec15b5 = get_latest_static_lib("llvmdev 15.* *_5", "osx-64")
    assert rec15b4.version.split(".")[0] == rec15b5.version.split(".")[0]
    assert rec15b4.build_number < rec15b5.build_number
    assert rec15b4.build_number == 4
    assert rec15b5.build_number == 5

    assert get_latest_static_lib("llvmdev 15.* *_100000", "osx-64") is None


@pytest.mark.parametrize(
    "recipe,expected_ood,expected_slrep",
    [
        (
            textwrap.dedent(
                """
                requirements:
                  host:
                    - llvm 15.*
                    - blah
                """
            )[1:-1],
            False,
            {"osx-64": {}, "osx-arm64": {}},
        ),
        (
            textwrap.dedent(
                """
                requirements:
                  host:
                    - {}
                    - llvm 15.*
                """.format(
                    get_latest_static_lib("llvm 15.*", "osx-64")
                    .to_match_spec()
                    .conda_build_form()
                )
            )[1:-1],
            False,
            {"osx-64": {}, "osx-arm64": {}},
        ),
        (
            textwrap.dedent(
                """
                requirements:
                  host:
                    - {}
                    - {}
                    - llvmdev 14.*
                    - llvm 14.*
                """.format(
                    get_latest_static_lib("llvmdev 13.*", "osx-64")
                    .to_match_spec()
                    .conda_build_form(),
                    _munge_hash_matchspec(
                        get_latest_static_lib("llvm 13.*", "osx-arm64")
                        .to_match_spec()
                        .conda_build_form()
                    ),
                )
            )[1:-1],
            True,
            {
                "osx-64": {
                    get_latest_static_lib("llvmdev 13.*", "osx-64")
                    .to_match_spec()
                    .conda_build_form(): get_latest_static_lib("llvmdev 14.*", "osx-64")
                    .to_match_spec()
                    .conda_build_form(),
                    _munge_hash_matchspec(
                        get_latest_static_lib("llvm 13.*", "osx-64")
                        .to_match_spec()
                        .conda_build_form()
                    ): _munge_hash_matchspec(
                        get_latest_static_lib("llvm 14.*", "osx-64")
                        .to_match_spec()
                        .conda_build_form()
                    ),
                },
                "osx-arm64": {
                    _munge_hash_matchspec(
                        get_latest_static_lib("llvm 13.*", "osx-arm64")
                        .to_match_spec()
                        .conda_build_form()
                    ): _munge_hash_matchspec(
                        get_latest_static_lib("llvm 14.*", "osx-arm64")
                        .to_match_spec()
                        .conda_build_form()
                    )
                },
            },
        ),
    ],
)
def test_staticlib_any_static_libs_out_of_date(recipe, expected_ood, expected_slrep):
    ood, slrep = any_static_libs_out_of_date(
        platform_arches=("osx-64", "osx-arm64"),
        raw_meta_yaml=recipe,
    )
    assert slrep == expected_slrep
    assert ood == expected_ood


@pytest.mark.parametrize(
    "input_meta_yaml,static_lib_replacements,final_meta_yaml",
    [
        (
            """
        requirements:
            host:
            - libfoo 10 h67_5
            - libfoo 10.*
            - libfoo 10 h2t_5
        """,
            {
                "osx-64": {"libfoo 10 h67_5": "libfoo 10 h66_6"},
                "osx-arm64": {"libfoo 10 h2t_5": "libfoo 10 ha6_6"},
            },
            """
        requirements:
            host:
            - libfoo 10 h66_6
            - libfoo 10.*
            - libfoo 10 ha6_6
        """,
        ),
        (
            """
        requirements:
            host:
            - libfoo 10 h67_5
            - libfoo 10.*
            - libfoo 10 h2t_5
        """,
            {
                "osx-64": {"libfoo 10 h67_3": "libfoo 10 h66_6"},
                "osx-arm64": {"libfoo 10 h2t_3": "libfoo 10 ha6_6"},
            },
            """
        requirements:
            host:
            - libfoo 10 h67_5
            - libfoo 10.*
            - libfoo 10 h2t_5
        """,
        ),
    ],
)
def test_staticlib_attempt_update_static_libs(
    input_meta_yaml, static_lib_replacements, final_meta_yaml
):
    expected_updated = input_meta_yaml != final_meta_yaml

    updated, output_meta_yaml = attempt_update_static_libs(
        input_meta_yaml, static_lib_replacements
    )
    assert output_meta_yaml == final_meta_yaml
    assert updated is expected_updated


@pytest.mark.parametrize(
    "yaml_path", [TEST_YAML_PATH, TEST_YAML_PATH_V1], ids=["v0", "v1"]
)
def test_staticlib_migrator_llvmlite(tmp_path, yaml_path):
    name = "llvmlite"
    with open(os.path.join(yaml_path, f"staticlib_{name}_before_meta.yaml")) as f:
        recipe_before = f.read()
    with open(os.path.join(yaml_path, f"staticlib_{name}_after_meta.yaml")) as f:
        recipe_after = f.read()

    kwargs = {"platforms": ["osx_64", "osx_arm64"]}

    dists = set()
    for platform in kwargs["platforms"]:
        for pkg in ["llvm", "llvmdev"]:
            ms = (
                get_latest_static_lib(pkg + " 15.*", platform)
                .to_match_spec()
                .conda_build_form()
            )
            dists.add(platform.replace("_", "-") + "::" + ms)

            if pkg == "llvmdev" and platform == "osx_arm64":
                pass
            elif pkg == "llvm" and platform == "osx_64":
                pass
            else:
                ms = _munge_hash_matchspec(ms)

            if yaml_path == TEST_YAML_PATH_V1:
                parts = ms.split(" ")
                ms = " ".join([parts[0], "==" + parts[1], parts[2]])

            recipe_after = recipe_after.replace(
                f"SUB@@{pkg.upper()}_{platform.upper()}@@",
                ms,
            )
    static_libs_uid = ";".join(sorted(dists))
    print("recipe after migration\n%s\n" % recipe_after)

    with open(tmp_path / "conda-forge.yml", "w") as fp:
        fp.write("bot: {update_static_libs: true}\n")

    # make the graph
    if yaml_path == TEST_YAML_PATH_V1:
        recipe_path = tmp_path / "recipe"
        recipe_path.mkdir(exist_ok=True)
        recipe_path.joinpath("recipe.yaml").write_text(recipe_before)
        pkwargs = {
            "recipe_yaml": recipe_before,
        }
        for tp in ["osx-arm64", "osx-64"]:
            ci_support_file = tmp_path / ".ci_support" / f"{tp.replace('-', '_')}_.yaml"
            ci_support_file.parent.mkdir(exist_ok=True)
            with open(
                ci_support_file,
                "w",
            ) as fp:
                fp.write(f"""\
    target_platform:
    - {tp}
    """)
    else:
        pkwargs = {
            "meta_yaml": recipe_before,
        }
    pmy = populate_feedstock_attributes(
        name,
        existing_node_attrs={},
        conda_forge_yaml="bot: {update_static_libs: true}\n",
        **pkwargs,
        feedstock_dir=tmp_path,
    )
    if yaml_path == TEST_YAML_PATH_V1:
        shutil.rmtree(tmp_path / "recipe", ignore_errors=True)
        shutil.rmtree(tmp_path / ".ci_support", ignore_errors=True)

    pmy["version"] = pmy["meta_yaml"]["package"]["version"]
    pmy["req"] = set()
    for k in ["build", "host", "run"]:
        req = pmy["meta_yaml"].get("requirements", {}) or {}
        _set = req.get(k) or set()
        pmy["req"] |= set(_set)
    pmy["raw_meta_yaml"] = recipe_before
    pmy.update(kwargs)

    graph = nx.DiGraph()
    graph.add_node(name, payload=pmy)
    graph.graph["outputs_lut"] = {}
    m = StaticLibMigrator(
        total_graph=graph,
    )
    run_test_migration(
        m=m,
        inp=recipe_before,
        output=recipe_after,
        kwargs=kwargs,
        prb="**statically linked libraries**",
        mr_out={
            "migrator_name": "StaticLibMigrator",
            "migrator_version": m.migrator_version,
            "name": "static_lib_migrator",
            "static_libs": static_libs_uid,
        },
        tmp_path=tmp_path,
        recipe_version=1 if yaml_path == TEST_YAML_PATH_V1 else 0,
    )
