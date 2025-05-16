from __future__ import annotations

import os

import networkx as nx
from test_migrators import run_test_migration, run_test_yaml_migration
from test_recipe_yaml_parsing import TEST_RECIPE_YAML_PATH

from conda_forge_tick.migrators import (
    MigrationYaml,
    Replacement,
    Version,
)


class NoFilter:
    def filter(self, attrs, not_bad_str_start=""):
        return False


class _MigrationYaml(NoFilter, MigrationYaml):
    pass


TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
yaml_rebuild = _MigrationYaml(yaml_contents="{}", name="hi", total_graph=TOTAL_GRAPH)
yaml_rebuild.cycles = []
yaml_rebuild_no_build_number = _MigrationYaml(
    yaml_contents="{}",
    name="hi",
    bump_number=0,
    total_graph=TOTAL_GRAPH,
)
yaml_rebuild_no_build_number.cycles = []


def sample_yaml_rebuild() -> str:
    yaml = TEST_RECIPE_YAML_PATH / "scipy_migrate.yaml"
    sample_yaml_rebuild = yaml.read_text()
    return sample_yaml_rebuild


def test_yaml_migration_rebuild(tmp_path):
    """Test that the build number is bumped."""
    sample = sample_yaml_rebuild()
    updated_yaml_rebuild = sample.replace("number: 0", "number: 1")

    run_test_yaml_migration(
        m=yaml_rebuild,
        inp=sample,
        output=updated_yaml_rebuild,
        kwargs={"feedstock_name": "scipy"},
        prb="This PR has been triggered in an effort to update **hi**.",
        mr_out={
            "migrator_name": yaml_rebuild.__class__.__name__,
            "migrator_version": yaml_rebuild.migrator_version,
            "name": "hi",
            "bot_rerun": False,
        },
        tmp_path=tmp_path,
        recipe_version=1,
    )


def test_yaml_migration_rebuild_no_buildno(tmp_path):
    sample = sample_yaml_rebuild()

    run_test_yaml_migration(
        m=yaml_rebuild_no_build_number,
        inp=sample,
        output=sample,
        kwargs={"feedstock_name": "scipy"},
        prb="This PR has been triggered in an effort to update **hi**.",
        mr_out={
            "migrator_name": yaml_rebuild.__class__.__name__,
            "migrator_version": yaml_rebuild.migrator_version,
            "name": "hi",
            "bot_rerun": False,
        },
        tmp_path=tmp_path,
        recipe_version=1,
    )


##################################################################
# Run Matplotlib mini-migrator                               ###
##################################################################

version = Version(set(), total_graph=TOTAL_GRAPH)

matplotlib = Replacement(
    old_pkg="matplotlib",
    new_pkg="matplotlib-base",
    rationale=(
        "Unless you need `pyqt`, recipes should depend only on `matplotlib-base`."
    ),
    pr_limit=5,
    total_graph=TOTAL_GRAPH,
)


class MockLazyJson:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


os.environ["RUN_URL"] = "hi world"


def test_generic_replacement(tmp_path):
    sample_matplotlib = TEST_RECIPE_YAML_PATH / "sample_matplotlib.yaml"
    sample_matplotlib = sample_matplotlib.read_text()
    sample_matplotlib_correct = sample_matplotlib.replace(
        "    - matplotlib", "    - matplotlib-base"
    )
    sample_matplotlib_correct = sample_matplotlib_correct.replace(
        "number: 0", "number: 1"
    )
    run_test_migration(
        m=matplotlib,
        inp=sample_matplotlib,
        output=sample_matplotlib_correct,
        kwargs={},
        prb="I noticed that this recipe depends on `matplotlib` instead of ",
        mr_out={
            "migrator_name": "Replacement",
            "migrator_version": matplotlib.migrator_version,
            "name": "matplotlib-to-matplotlib-base",
        },
        tmp_path=tmp_path,
        recipe_version=1,
    )
