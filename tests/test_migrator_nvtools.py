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


def store_file_contents(filename):
    with open(filename) as file:
        return file.read()


def write_file_contents(filename, buffer):
    with open(filename, "w") as file:
        file.write(buffer)


def test_nvtools_migrate(test_graph):
    backups = [
        store_file_contents(os.path.join(mock_recipe_dir, f))
        for f in ["build.sh", "meta.yaml", "../conda-forge.yml"]
    ]

    migrator = AddNVIDIATools(total_graph=test_graph)
    migrator.migrate(
        mock_recipe_dir,
        mock_node_attrs,
    )
    try:
        filecmp.cmp(
            os.path.join(mock_recipe_dir, "build.sh"),
            os.path.join(mock_recipe_dir_ref, "build.sh"),
            shallow=False,
        )
        filecmp.cmp(
            os.path.join(mock_recipe_dir, "meta.yaml"),
            os.path.join(mock_recipe_dir_ref, "meta.yaml"),
            shallow=False,
        )
        filecmp.cmp(
            os.path.join(mock_recipe_dir, "..", "conda-forge.yml"),
            os.path.join(mock_recipe_dir_ref, "..", "conda-forge.yml"),
            shallow=False,
        )
    except Exception as e:
        raise e
    finally:
        [
            write_file_contents(os.path.join(mock_recipe_dir, f), b)
            for f, b in zip(["build.sh", "meta.yaml", "../conda-forge.yml"], backups)
        ]
