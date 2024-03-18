import os

import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import QtQtMainMigrator, Version

QTQTMAIN = QtQtMainMigrator()
VERSION_WITH_QTQTMAIN = Version(
    set(),
    piggy_back_migrations=[QTQTMAIN],
)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


@pytest.mark.parametrize(
    "old_meta,new_meta,new_ver",
    [
        (
            "qtqtmain_octave_before_meta.yaml",
            "qtqtmain_octave_after_meta.yaml",
            "7.1.0",
        ),
        ("qtqtmain_qgis_before_meta.yaml", "qtqtmain_qgis_after_meta.yaml", "3.18.3"),
    ],
)
def test_qt_main(old_meta, new_meta, new_ver, tmpdir):
    with open(os.path.join(YAML_PATH, old_meta)) as fp:
        in_yaml = fp.read()

    with open(os.path.join(YAML_PATH, new_meta)) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_WITH_QTQTMAIN,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": VERSION_WITH_QTQTMAIN.migrator_version,
            "version": new_ver,
        },
        tmpdir=tmpdir,
        should_filter=False,
    )
