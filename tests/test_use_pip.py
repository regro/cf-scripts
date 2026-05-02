import os

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import PipMigrator, Version

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
PC = PipMigrator()
VERSION_PC = Version(set(), piggy_back_migrations=[PC], total_graph=TOTAL_GRAPH)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


@pytest.mark.parametrize("case", ["simple", "selector"])
def test_version_pipcheck(case, tmp_path):
    with open(os.path.join(YAML_PATH, "version_usepip_%s.yaml" % case)) as fp:
        in_yaml = fp.read()

    with open(
        os.path.join(YAML_PATH, "version_usepip_%s_correct.yaml" % case),
    ) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_PC,
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
    )
