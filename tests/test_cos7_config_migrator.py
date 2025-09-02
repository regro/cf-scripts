import os

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import Cos7Config, Version
from conda_forge_tick.migrators.cos7 import REQUIRED_RE_LINES, _has_line_set

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
VERSION_COS7 = Version(
    set(),
    piggy_back_migrations=[Cos7Config()],
    total_graph=TOTAL_GRAPH,
)

YAML_PATHS = [
    os.path.join(os.path.dirname(__file__), "test_yaml"),
    os.path.join(os.path.dirname(__file__), "test_v1_yaml"),
]


@pytest.mark.parametrize("remove_quay", [False, True])
@pytest.mark.parametrize("case", list(range(len(REQUIRED_RE_LINES))))
@pytest.mark.parametrize("recipe_version", [0, 1])
def test_version_cos7_config(case, remove_quay, recipe_version, tmp_path):
    with open(
        os.path.join(YAML_PATHS[recipe_version], "version_cos7_config_simple.yaml")
    ) as fp:
        in_yaml = fp.read()

    with open(
        os.path.join(
            YAML_PATHS[recipe_version], "version_cos7_config_simple_correct.yaml"
        ),
    ) as fp:
        out_yaml = fp.read()

    tmp_path.joinpath("recipe").mkdir()
    cfg = tmp_path / "recipe/conda_build_config.yaml"

    with open(cfg, "w") as fp:
        for i, (_, _, first, second) in enumerate(REQUIRED_RE_LINES):
            if i != case:
                fp.write(first + "\n")
                if "docker_image" in first and remove_quay:
                    fp.write(
                        second.replace("quay.io/condaforge/", "condaforge/") + "\n",
                    )

    run_test_migration(
        m=VERSION_COS7,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )
    with open(cfg) as fp:
        cfg_lines = fp.readlines()

    for first_re, second_re, first, second in REQUIRED_RE_LINES:
        assert _has_line_set(cfg_lines, first_re, second_re), (first, second)


@pytest.mark.parametrize("case", list(range(len(REQUIRED_RE_LINES))))
@pytest.mark.parametrize("recipe_version", [0, 1])
def test_version_cos7_config_skip(case, recipe_version, tmp_path):
    with open(
        os.path.join(YAML_PATHS[recipe_version], "version_cos7_config_simple.yaml")
    ) as fp:
        in_yaml = fp.read()

    with open(
        os.path.join(
            YAML_PATHS[recipe_version], "version_cos7_config_simple_correct.yaml"
        ),
    ) as fp:
        out_yaml = fp.read()

    tmp_path.joinpath("recipe").mkdir()
    cfg = tmp_path / "recipe/conda_build_config.yaml"

    with open(cfg, "w") as fp:
        for i, (_, _, first, second) in enumerate(REQUIRED_RE_LINES):
            if i != case:
                fp.write(first + "blarg\n")
                fp.write(second + "blarg\n")

    run_test_migration(
        m=VERSION_COS7,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmp_path=tmp_path,
        recipe_version=recipe_version,
    )
    with open(cfg) as fp:
        cfg_lines = fp.readlines()

    for i, (first_re, second_re, first, second) in enumerate(REQUIRED_RE_LINES):
        if i != case:
            assert _has_line_set(cfg_lines, first_re, second_re), (first, second)
