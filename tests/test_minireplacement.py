from pathlib import Path

import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import MiniReplacement, Version

XZLIBLZMADEVEL = MiniReplacement(old_pkg="xz", new_pkg="liblzma-devel")
VERSION_WITH_XZLIBLZMADEVEL = Version(
    set(),
    piggy_back_migrations=[XZLIBLZMADEVEL],
)

YAML_PATHS = [
    Path(__file__).parent / "test_yaml",
    Path(__file__).parent / "test_v1_yaml",
]


@pytest.mark.parametrize(
    "old_meta,new_meta,new_ver",
    [
        (
            "libtiff_with_xz.yaml",
            "libtiff_with_liblzma_devel.yaml",
            "4.7.0",
        ),
    ],
)
@pytest.mark.parametrize("recipe_version", [0, 1])
def test_liblzma_devel(old_meta, new_meta, new_ver, recipe_version, tmp_path):
    run_test_migration(
        m=VERSION_WITH_XZLIBLZMADEVEL,
        inp=YAML_PATHS[recipe_version].joinpath(old_meta).read_text(),
        output=YAML_PATHS[recipe_version].joinpath(new_meta).read_text(),
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": VERSION_WITH_XZLIBLZMADEVEL.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
        should_filter=False,
        recipe_version=recipe_version,
    )
