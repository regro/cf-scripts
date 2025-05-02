import os

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import DuplicateLinesCleanup, Version

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
VERSION_DLC = Version(
    set(),
    piggy_back_migrations=[DuplicateLinesCleanup()],
    total_graph=TOTAL_GRAPH,
)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


@pytest.mark.parametrize(
    "slug,clean_slug",
    [
        ("noarch: generic", "noarch: generic"),
        ("noarch: python", "noarch: python"),
        ("noarch:   generic     ", "noarch: generic"),
        ("noarch:   python     ", "noarch: python"),
    ],
)
def test_version_duplicate_lines_cleanup(slug, clean_slug, tmp_path):
    with open(os.path.join(YAML_PATH, "version_duplicate_lines_cleanup.yaml")) as fp:
        in_yaml = fp.read()

    with open(
        os.path.join(YAML_PATH, "version_duplicate_lines_cleanup_correct.yaml"),
    ) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_DLC,
        inp=in_yaml.replace("@@SLUG@@", slug),
        output=out_yaml.replace("@@SLUG@@", clean_slug),
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmp_path=tmp_path,
    )


@pytest.mark.parametrize(
    "slug,clean_slug",
    [
        ("noarch: generic", "noarch: generic"),
        ("noarch: python", "noarch: python"),
        ("noarch:   generic     ", "noarch: generic"),
        ("noarch:   python     ", "noarch: python"),
    ],
)
def test_version_duplicate_lines_cleanup_skip(slug, clean_slug, tmp_path):
    with open(
        os.path.join(YAML_PATH, "version_duplicate_lines_cleanup_skip.yaml"),
    ) as fp:
        in_yaml = fp.read()

    with open(
        os.path.join(YAML_PATH, "version_duplicate_lines_cleanup_skip_correct.yaml"),
    ) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_DLC,
        inp=in_yaml.replace("@@SLUG@@", slug),
        output=out_yaml.replace("@@SLUG@@", clean_slug),
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmp_path=tmp_path,
    )
