import os
import pprint
import subprocess

import networkx as nx
from test_migrators import sample_yaml_rebuild, updated_yaml_rebuild

from conda_forge_tick.migration_runner import run_migration_local
from conda_forge_tick.migrators import MigrationYaml
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import parse_meta_yaml


class NoFilter:
    def filter(self, attrs, not_bad_str_start=""):
        return False


class _MigrationYaml(NoFilter, MigrationYaml):
    pass


TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
yaml_rebuild = _MigrationYaml(yaml_contents="{}", name="hi", total_graph=TOTAL_GRAPH)
yaml_rebuild.cycles = []


def test_migration_runner_run_migration_local_yaml_rebuild(tmpdir):
    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    with open(os.path.join(tmpdir, "recipe", "meta.yaml"), "w") as f:
        f.write(sample_yaml_rebuild)

    with pushd(tmpdir):
        subprocess.run(["git", "init", "-b", "main"])
    # Load the meta.yaml (this is done in the graph)
    try:
        pmy = parse_meta_yaml(sample_yaml_rebuild)
    except Exception:
        pmy = {}
    if pmy:
        pmy["version"] = pmy["package"]["version"]
        pmy["req"] = set()
        for k in ["build", "host", "run"]:
            pmy["req"] |= set(pmy.get("requirements", {}).get(k, set()))
        try:
            pmy["meta_yaml"] = parse_meta_yaml(sample_yaml_rebuild)
        except Exception:
            pmy["meta_yaml"] = {}
    pmy["raw_meta_yaml"] = sample_yaml_rebuild

    migration_data = run_migration_local(
        migrator=yaml_rebuild,
        feedstock_dir=tmpdir,
        feedstock_name="scipy",
        node_attrs=pmy,
        default_branch="main",
    )

    pprint.pprint(migration_data)

    assert migration_data["migrate_return_value"] == {
        "migrator_name": yaml_rebuild.__class__.__name__,
        "migrator_version": yaml_rebuild.migrator_version,
        "name": "hi",
        "bot_rerun": False,
    }
    assert migration_data["commit_message"] == "Rebuild for hi"
    assert migration_data["pr_title"] == "Rebuild for hi"
    assert migration_data["pr_body"].startswith(
        "This PR has been triggered in an effort to update "
        "[**hi**](https://conda-forge.org/status/migration/?name=hi)."
    )

    with open(os.path.join(tmpdir, "recipe/meta.yaml")) as f:
        actual_output = f.read()
    assert actual_output == updated_yaml_rebuild
    assert os.path.exists(os.path.join(tmpdir, ".ci_support/migrations/hi.yaml"))
    with open(os.path.join(tmpdir, ".ci_support/migrations/hi.yaml")) as f:
        saved_migration = f.read()
    assert saved_migration == yaml_rebuild.yaml_contents
