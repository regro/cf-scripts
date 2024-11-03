import os

import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import FlangMigrator, Version

TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


FLANG = FlangMigrator()
VERSION_WITH_FLANG = Version(
    set(),
    piggy_back_migrations=[FLANG],
)


@pytest.mark.parametrize(
    "feedstock,new_ver",
    [
        # multiple outputs
        ("lapack", "1.10.0"),
        # comments in compiler block
        ("prima", "1.10.0"),
    ],
)
def test_stdlib(feedstock, new_ver, tmpdir):
    before = f"flang_{feedstock}_before_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, before)) as fp:
        in_yaml = fp.read()

    after = f"flang_{feedstock}_after_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, after)) as fp:
        out_yaml = fp.read()

    recipe_dir = os.path.join(tmpdir, f"{feedstock}-feedstock")
    os.makedirs(recipe_dir, exist_ok=True)

    run_test_migration(
        m=VERSION_WITH_FLANG,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": VERSION_WITH_FLANG.migrator_version,
            "version": new_ver,
        },
        tmpdir=recipe_dir,
        should_filter=False,
    )
