import os

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import PyPIOrgMigrator, Version

TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
PYPI_ORG = PyPIOrgMigrator()
VERSION_WITH_PYPI_ORG = Version(
    set(),
    piggy_back_migrations=[PYPI_ORG],
    total_graph=TOTAL_GRAPH,
)


@pytest.mark.parametrize(
    "feedstock,new_ver",
    [
        ("seaborn", "0.13.2"),
    ],
)
def test_pypi_org(feedstock, new_ver, tmp_path):
    before = f"pypi_org_{feedstock}_before_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, before)) as fp:
        in_yaml = fp.read()

    after = f"pypi_org_{feedstock}_after_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, after)) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_WITH_PYPI_ORG,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": VERSION_WITH_PYPI_ORG.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
        should_filter=False,
    )
