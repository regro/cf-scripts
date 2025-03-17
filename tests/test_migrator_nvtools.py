import filecmp
import os.path

from conda_forge_tick.migrators import AddNVIDIATools

mock_recipe_dir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mock_nvtools_migrator_feedstock",
    "recipe",
)

mock_recipe_dir_ref = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "mock_nvtools_migrator_feedstock_ref",
    "recipe",
)

mock_node_attrs = {}


def test_nvtools_migrate():
    migrator = AddNVIDIATools()
    migrator.migrate(
        mock_recipe_dir,
        mock_node_attrs,
    )
    assert filecmp.cmp(
        os.path.join(mock_recipe_dir, "build.sh"),
        os.path.join(mock_recipe_dir_ref, "build.sh"),
        shallow=False,
    )
    assert filecmp.cmp(
        os.path.join(mock_recipe_dir, "meta.yaml"),
        os.path.join(mock_recipe_dir_ref, "meta.yaml"),
        shallow=False,
    )
    assert filecmp.cmp(
        os.path.join(mock_recipe_dir, "..", "conda-forge.yml"),
        os.path.join(mock_recipe_dir_ref, "..", "conda-forge.yml"),
        shallow=False,
    )
