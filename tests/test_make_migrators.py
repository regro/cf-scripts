import os
import shutil
import tempfile
from pathlib import Path

import pytest

from conda_forge_tick.lazy_json_backends import get_sharded_path
from conda_forge_tick.make_migrators import create_migration_yaml_creator
from conda_forge_tick.migrators import MigrationYamlCreator
from conda_forge_tick.utils import load_existing_graph

TEST_FILES_DIR = Path(__file__).parent / "test_files_make_migrators"
TEST_GRAPH_FILE = TEST_FILES_DIR / "test_graph.json"
TEST_CONDA_BUILD_CONFIG_FILE = TEST_FILES_DIR / "test_conda_build_config.yaml"

CONDA_FORGE_PINNINGS_ATTRS_FILE = TEST_FILES_DIR / "conda-forge-pinning_node_attrs.json"
NUMPY_NODE_ATTRS_FILE = TEST_FILES_DIR / "numpy_node_attrs.json"


class TestCreateMigrationYamlCreator:
    @pytest.fixture
    def inject_conda_build_config(self):
        with tempfile.TemporaryDirectory(prefix="cf-graph") as s_tmpdir:
            conda_prefix_dir = Path(s_tmpdir)
            shutil.copy(
                TEST_CONDA_BUILD_CONFIG_FILE,
                conda_prefix_dir / "conda_build_config.yaml",
            )

            old_conda_prefix = os.environ["CONDA_PREFIX"]
            os.environ["CONDA_PREFIX"] = str(conda_prefix_dir)
            yield
            os.environ["CONDA_PREFIX"] = old_conda_prefix

    @pytest.fixture
    def prepared_graph(self):
        with tempfile.TemporaryDirectory(prefix="cf-graph") as s_tmpdir:
            cf_graph_dir = Path(s_tmpdir)
            shutil.copy(TEST_GRAPH_FILE, cf_graph_dir / "graph.json")

            numpy_dest = cf_graph_dir / get_sharded_path("node_attrs/numpy.json")
            os.makedirs(numpy_dest.parent, exist_ok=True)
            shutil.copy(NUMPY_NODE_ATTRS_FILE, numpy_dest)

            pinning_dest = cf_graph_dir / get_sharded_path(
                "node_attrs/conda-forge-pinning.json"
            )
            os.makedirs(pinning_dest.parent, exist_ok=True)
            shutil.copy(CONDA_FORGE_PINNINGS_ATTRS_FILE, pinning_dest)

            old_cwd = os.getcwd()
            os.chdir(cf_graph_dir)
            yield load_existing_graph()
            os.chdir(old_cwd)

    def test_successful_recipe_v0(self, prepared_graph, inject_conda_build_config):
        migrators: list[MigrationYamlCreator] = []
        create_migration_yaml_creator(migrators, prepared_graph)

        assert len(migrators) == 1
        migrator = migrators[0]

        assert migrator.feedstock_name == "numpy"
        assert migrator.package_name == "numpy"
        assert migrator.current_pin == "1.26"
        assert migrator.new_pin_version == "2"
        assert migrator.pin_spec == "x"

        assert len(migrator.effective_graph) == 1
        assert "conda-forge-pinning" in migrator.effective_graph
