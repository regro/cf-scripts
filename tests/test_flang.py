import os

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import FlangMigrator, Version

TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
FLANG = FlangMigrator()
VERSION_WITH_FLANG = Version(
    set(),
    piggy_back_migrations=[FLANG],
    total_graph=TOTAL_GRAPH,
)


@pytest.mark.parametrize(
    "feedstock,new_ver",
    [
        # multiple outputs
        ("lapack", "1.10.0"),
        # comments in compiler block
        ("prima", "1.10.0"),
        # remove selector for non-m2w64 fortran compilers
        ("mfront", "1.10.0"),
        # includes cxx (non-m2w64) as a language
        ("plplot", "1.10.0"),
        # includes m2w64_cxx compiler
        ("pcmsolver-split", "1.10.0"),
    ],
)
def test_flang(feedstock, new_ver, tmp_path):
    before = f"flang_{feedstock}_before_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, before)) as fp:
        in_yaml = fp.read()

    after = f"flang_{feedstock}_after_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, after)) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_WITH_FLANG,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": VERSION_WITH_FLANG.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
        should_filter=False,
    )
