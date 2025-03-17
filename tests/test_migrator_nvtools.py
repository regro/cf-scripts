import os.path

from conda_forge_tick.migrators import AddNVIDIATools

mock_recipe_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mock_nvtools_migrator_feedstock",
    "recipe",
)

mock_node_attrs = {}


def test_nvtools_migrate():
    migrator = AddNVIDIATools()
    migrator.migrate(
        mock_recipe_dir,
        mock_node_attrs,
    )
