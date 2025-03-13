import os

import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import Version, XzLibLzmaDevelMigrator

XZLIBLZMADEVEL = XzLibLzmaDevelMigrator()
VERSION_WITH_XZLIBLZMADEVEL = Version(
    set(),
    piggy_back_migrations=[XZLIBLZMADEVEL],
)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


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
def test_liblzma_devel(old_meta, new_meta, new_ver, tmp_path):
    with open(os.path.join(YAML_PATH, old_meta)) as fp:
        in_yaml = fp.read()

    with open(os.path.join(YAML_PATH, new_meta)) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_WITH_XZLIBLZMADEVEL,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": VERSION_WITH_XZLIBLZMADEVEL.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
        should_filter=False,
    )
