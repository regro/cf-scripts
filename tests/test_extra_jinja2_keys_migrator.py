import os

import networkx as nx
from test_migrators import run_test_migration

from conda_forge_tick.migrators import ExtraJinja2KeysCleanup, Version

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
VERSION_CF = Version(
    set(),
    piggy_back_migrations=[ExtraJinja2KeysCleanup()],
    total_graph=TOTAL_GRAPH,
)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


def test_version_extra_jinja2_keys_cleanup(tmp_path):
    with open(os.path.join(YAML_PATH, "version_extra_jinja2_keys.yaml")) as fp:
        in_yaml = fp.read()

    with open(
        os.path.join(YAML_PATH, "version_extra_jinja2_keys_correct.yaml"),
    ) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_CF,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.20.0"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.20.0",
        },
        tmp_path=tmp_path,
    )
