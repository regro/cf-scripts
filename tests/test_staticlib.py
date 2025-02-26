import os
import textwrap

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.feedstock_parser import populate_feedstock_attributes
from conda_forge_tick.migrators.staticlib import (
    StaticLibMigrator,
    _cached_dist_from_str,
    _cached_match_spec,
    _left_gt_right_dist,
    _match_spec_is_exact,
    _match_spec_to_dist,
    any_static_libs_out_of_date,
    attempt_update_static_libs,
    extract_static_libs_from_meta_yaml_text,
    get_latest_static_lib,
)

TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


@pytest.mark.parametrize(
    "ld,rd,res",
    [
        (
            _cached_dist_from_str("libfoo-0.9.0-h1234_0"),
            _cached_dist_from_str("libfoo-1.0.0-h1234_0"),
            False,
        ),
        (
            _cached_dist_from_str("libfoo-1.0.0-h1234_0"),
            _cached_dist_from_str("libfoo-1.0.0-h1234_0"),
            False,
        ),
        (
            _cached_dist_from_str("libfoo-1.0.0-h1234_0"),
            _cached_dist_from_str("libfoo-1.0.0-h1234_1"),
            False,
        ),
        (
            _cached_dist_from_str("libfoo-1.0.0-h1234_1"),
            _cached_dist_from_str("libfoo-1.0.0-h1234_0"),
            True,
        ),
        (
            _cached_dist_from_str("libfoo-1.0.1-h1234_0"),
            _cached_dist_from_str("libfoo-1.0.0-h1234_0"),
            True,
        ),
        (
            _cached_dist_from_str("libfoo-1.0.1-h1234_0"),
            _cached_dist_from_str("libfoo-1.0.0-h1234_1"),
            True,
        ),
    ],
)
def test_left_gt_right_dist(ld, rd, res):
    assert _left_gt_right_dist(ld, rd) is res
    if ld != rd:
        assert _left_gt_right_dist(rd, ld) is (not res)


@pytest.mark.parametrize(
    "mstr,res",
    [
        ("libfoo * *", False),
        ("libfoo >=10", False),
        ("libfoo", False),
        ("libfoo ==10 *_6", False),
        ("libfoo 10 h67_5", True),
        ("libfoo 10.* h67_5", False),
    ],
)
def test_staticlib_match_spec_is_exact(mstr, res):
    assert _match_spec_is_exact(_cached_match_spec(mstr)) is res


def test_staticlib_match_spec_to_dist_works():
    mstr = _cached_match_spec("libfoo 10 h67_5")
    dist = _match_spec_to_dist(mstr)
    assert dist.name == mstr.get_exact_value("name")
    assert dist.version == mstr.get_exact_value("version")
    assert dist.build == mstr.get_exact_value("build")


def test_staticlib_match_spec_to_dist_raises():
    with pytest.raises(ValueError):
        _match_spec_to_dist(_cached_match_spec("libfoo >=10"))


def test_staticlib_get_latest_static_lib():
    ld = get_latest_static_lib("llvmdev", "osx-64")
    ld15 = get_latest_static_lib("llvmdev 15.*", "osx-64")
    assert ld.version.split(".")[0] > ld15.version.split(".")[0]

    ld15b4 = get_latest_static_lib("llvmdev 15.* *_4", "osx-64")
    ld15b5 = get_latest_static_lib("llvmdev 15.* *_5", "osx-64")
    assert ld15b4.version.split(".")[0] == ld15b5.version.split(".")[0]
    assert ld15b4.build_number < ld15b5.build_number
    assert ld15b4.build_number == 4
    assert ld15b5.build_number == 5

    with pytest.raises(ValueError):
        get_latest_static_lib("llvmdev 15.* *_100000", "osx-64")


@pytest.mark.parametrize(
    "meta_yaml_text,slhr,expected",
    [
        (
            (
                textwrap.dedent(
                    """
                    host:
                      - libfoo 10 h67_5
                      - libfoo 10.*
                      # libfood 10 h2t_4
                      {% random jinja %}

                      - libbar 10 h2t_4
                    """
                )[1:-1],
                textwrap.dedent(
                    """
                    host:
                      - libfoo 10.*
                      - libbar 10 h2t_4
                    """
                )[1:-1],
            ),
            "libfoo 10.*",
            {"libfoo 10 h67_5"},
        ),
        (
            (
                textwrap.dedent(
                    """
                    host:
                      - libfoo 10 h67_5
                      - libfoo 10.*
                      - libfoo 10 h2t_4
                    """
                )[1:-1],
                textwrap.dedent(
                    """
                    host:
                      - libfoo 10.*
                      - libbar 10 h2t_4
                    """
                )[1:-1],
            ),
            "libfoo 10.*",
            {"libfoo 10 h67_5", "libfoo 10 h2t_4"},
        ),
        (
            (
                textwrap.dedent(
                    """
                    host:
                      - libfoo 10 h67_5
                      - libfoo 10.*
                      - libbar 10 h2t_4
                    """
                )[1:-1],
            ),
            "libfoo 10.*",
            {"libfoo 10 h67_5"},
        ),
        (
            (
                textwrap.dedent(
                    """
                    host:
                      - libfoo 10 h67_5
                      - libfoo 10.*
                      - libbar 10 h2t_4
                    """
                )[1:-1],
                textwrap.dedent(
                    """
                    host:
                      - libfoo 10.*
                      - libbar 10 h2t_4
                    """
                )[1:-1],
            ),
            "libf 10.*",
            set(),
        ),
        (
            (
                textwrap.dedent(
                    """
                    host:
                      - libfoo 10 h67_5
                      - libfoo 10.*
                      - libbar 10 h2t_4
                    """
                )[1:-1],
            ),
            "libf 10.*",
            set(),
        ),
    ],
)
def test_staticlib_extract_static_libs_from_meta_yaml_text(
    meta_yaml_text, slhr, expected
):
    static_libs = extract_static_libs_from_meta_yaml_text(meta_yaml_text, slhr)
    static_libs = {sl.to_matchspec() for sl in static_libs}
    assert static_libs == expected


@pytest.mark.parametrize(
    "recipe,slhr,expected_ood,expected_slrep",
    [
        (
            textwrap.dedent(
                """
                requirements:
                  host:
                    - blah
                """
            )[1:-1],
            ("llvm 15.*",),
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
                """.format(get_latest_static_lib("llvm 15.*", "osx-64").to_matchspec())
            )[1:-1],
            ("llvm 15.*",),
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
                """.format(
                    get_latest_static_lib("llvm 13.*", "osx-64").to_matchspec(),
                    get_latest_static_lib("llvm 13.*", "osx-arm64").to_matchspec(),
                )
            )[1:-1],
            ("llvm 14.*",),
            True,
            {
                "osx-64": {
                    get_latest_static_lib(
                        "llvm 13.*", "osx-64"
                    ).to_matchspec(): get_latest_static_lib(
                        "llvm 14.*", "osx-64"
                    ).to_matchspec()
                },
                "osx-arm64": {
                    get_latest_static_lib(
                        "llvm 13.*", "osx-arm64"
                    ).to_matchspec(): get_latest_static_lib(
                        "llvm 14.*", "osx-arm64"
                    ).to_matchspec()
                },
            },
        ),
    ],
)
def test_staticlib_any_static_libs_out_of_date(
    recipe, slhr, expected_ood, expected_slrep
):
    ood, slrep = any_static_libs_out_of_date(
        static_linking_host_requirements=slhr,
        platform_arches=("osx-64", "osx-arm64"),
        raw_meta_yaml=recipe,
    )
    assert ood == expected_ood
    assert slrep == expected_slrep


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


def test_staticlib_migrator_llvmlite(tmpdir):
    name = "llvmlite"
    with open(os.path.join(TEST_YAML_PATH, f"staticlib_{name}_before_meta.yaml")) as f:
        recipe_before = f.read()
    with open(os.path.join(TEST_YAML_PATH, f"staticlib_{name}_after_meta.yaml")) as f:
        recipe_after = f.read()

    kwargs = {"platforms": ["osx_64", "osx_arm64"]}

    dists = set()
    for platform in kwargs["platforms"]:
        for pkg in ["llvm", "llvmdev"]:
            ms = get_latest_static_lib(pkg + " 15.*", platform).to_matchspec()
            dists.add(platform.replace("_", "-") + "::" + ms)

            recipe_after = recipe_after.replace(
                f"SUB@@{pkg.upper()}_{platform.upper()}@@",
                ms,
            )
    static_libs_uid = ";".join(sorted(dists))
    print("recipe after migration\n%s\n" % recipe_after)

    # make the graph
    pmy = populate_feedstock_attributes(
        name, sub_graph={}, meta_yaml=recipe_before, conda_forge_yaml="{}"
    )

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
    m = StaticLibMigrator(
        graph=graph,
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
        tmpdir=tmpdir,
    )
