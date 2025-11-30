import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import networkx as nx
import pytest
from pytest import FixtureRequest

from conda_forge_tick.lazy_json_backends import (
    get_sharded_path,
    lazy_json_override_backends,
)
from conda_forge_tick.make_migrators import (
    create_migration_yaml_creator,
    dump_migrators,
    initialize_migrators,
    load_migrators,
)
from conda_forge_tick.migrators import MigrationYaml, MigrationYamlCreator
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import load_existing_graph, load_graph, pluck

TEST_FILES_DIR = Path(__file__).parent / "test_files_make_migrators"
TEST_GRAPH_FILE = TEST_FILES_DIR / "test_graph.json"
TEST_CONDA_BUILD_CONFIG_FILE = TEST_FILES_DIR / "test_conda_build_config.yaml"

CONDA_FORGE_PINNINGS_ATTRS_FILE = TEST_FILES_DIR / "conda-forge-pinning_node_attrs.json"
NUMPY_NODE_ATTRS_FILE = TEST_FILES_DIR / "numpy_node_attrs.json"


@pytest.mark.parametrize("enable_containers", [True, False])
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
    def prepared_graph(self, request: pytest.FixtureRequest):
        """
        Get the graph with the node attrs files that should be present in the
        graph as indirect fixture parameters.
        """
        node_attrs_files: list[str] = request.param

        with tempfile.TemporaryDirectory(prefix="cf-graph") as s_tmpdir:
            cf_graph_dir = Path(s_tmpdir)
            shutil.copy(TEST_GRAPH_FILE, cf_graph_dir / "graph.json")

            for node_attrs_file in node_attrs_files:
                origin = TEST_FILES_DIR / f"{node_attrs_file}_node_attrs.json"
                dest = cf_graph_dir / get_sharded_path(
                    f"node_attrs/{node_attrs_file}.json"
                )
                os.makedirs(dest.parent, exist_ok=True)
                shutil.copy(origin, dest)

            old_cwd = os.getcwd()
            os.chdir(cf_graph_dir)
            yield load_existing_graph()
            os.chdir(old_cwd)

    @pytest.mark.parametrize(
        "prepared_graph", [["conda-forge-pinning", "numpy"]], indirect=True
    )
    def test_successful_recipe_v0(
        self,
        prepared_graph: nx.DiGraph,
        inject_conda_build_config,
        enable_containers: bool,
        request: FixtureRequest,
    ):
        if enable_containers:
            request.getfixturevalue("use_containers")

        # feedstock under test: numpy
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

    @pytest.mark.parametrize(
        "prepared_graph", [["conda-forge-pinning", "aws-c-io"]], indirect=True
    )
    def test_successful_recipe_v1(
        self,
        prepared_graph: nx.DiGraph,
        inject_conda_build_config,
        enable_containers: bool,
        request: FixtureRequest,
    ):
        if enable_containers:
            request.getfixturevalue("use_containers")

        # feedstock under test: aws-c-io
        migrators: list[MigrationYamlCreator] = []
        create_migration_yaml_creator(migrators, prepared_graph)

        assert len(migrators) == 1
        migrator = migrators[0]

        assert migrator.feedstock_name == "aws-c-io"
        assert migrator.package_name == "aws_c_io"
        assert migrator.current_pin == "0.15.3"
        assert migrator.new_pin_version == "0.18.0"
        assert migrator.pin_spec == "x.x.x"

        assert len(migrator.effective_graph) == 1
        assert "conda-forge-pinning" in migrator.effective_graph


def test_make_migrators_initialize_migrators():
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth=1",
                "https://github.com/regro/cf-graph-countyfair.git",
            ],
            cwd=tmpdir,
            check=True,
        )
        with (
            pushd(os.path.join(tmpdir, "cf-graph-countyfair")),
            lazy_json_override_backends(["file"], use_file_cache=True),
        ):
            gx = load_graph()

            assert "payload" in gx.nodes["conda-forge-pinning"], (
                "Payload not found for conda-forge-pinning!"
            )

            nodes_to_keep = set()
            # random selection of packages to cut the graph down
            nodes_to_test = [
                "ngmix",
                "ultraplot",
                "r-semaphore",
                "r-tidyverse",
                "conda-forge-pinning",
            ]
            while nodes_to_test:
                pkg = nodes_to_test.pop(0)
                if pkg in gx.nodes:
                    nodes_to_keep.add(pkg)
                    for n in gx.predecessors(pkg):
                        if n not in nodes_to_keep:
                            nodes_to_test.append(n)

            for pkg in set(gx.nodes) - nodes_to_keep:
                pluck(gx, pkg)

            # post plucking cleanup
            gx.remove_edges_from(nx.selfloop_edges(gx))

            print(
                "Number of nodes in the graph after plucking:",
                len(gx.nodes),
                flush=True,
            )

            migrators = initialize_migrators(gx)

            assert len(migrators) > 0, "No migrators found!"
            for migrator in migrators:
                assert migrator is not None, "Migrator is None!"
                assert hasattr(migrator, "effective_graph"), (
                    "Migrator has no effective graph!"
                )
                assert hasattr(migrator, "graph"), "Migrator has no graph attribute!"
                if isinstance(migrator, MigrationYaml):
                    assert "conda-forge-pinning" in migrator.graph.nodes

            # dump and load the migrators
            dump_migrators(migrators)
            load_migrators(skip_paused=False)


@pytest.mark.parametrize(
    "filter_name, expected_names",
    [
        (None, ["python314", "python314t", "python315", "compilers"]),
        (["python"], ["python314", "python314t", "python315"]),
        (["PYTHON"], ["python314", "python314t", "python315"]),
        (["python314"], ["python314", "python314t"]),
        (["compilers"], ["compilers"]),
        (["python314", "python315"], ["python314", "python314t", "python315"]),
        (
            ["python", "compilers"],
            ["python314", "python314t", "python315", "compilers"],
        ),
        (["nonexistent"], []),
    ],
)
def test_load_migrators_filter_name(filter_name, expected_names):
    """Test that load_migrators filters migrators by name correctly."""
    from unittest.mock import patch

    mock_migrator_names = [
        "python314",
        "python314t",
        "python315",
        "compilers",
    ]

    with patch(
        "conda_forge_tick.make_migrators.get_all_keys_for_hashmap"
    ) as mock_get_keys:
        mock_get_keys.return_value = mock_migrator_names

        with patch("conda_forge_tick.make_migrators._load_migrators") as mock_load:
            mock_load.return_value = []
            _ = load_migrators(skip_paused=True, filter_name=filter_name)
            assert mock_get_keys.called
            mock_load.assert_called_once_with(expected_names, skip_paused=True)
