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
            ("qtqtmain_octave_after_meta.yaml", "qtqtmain_octave_xz_after_meta.yaml"),
            "7.1.0",
        ),
        ("qtqtmain_qgis_before_meta.yaml", "qtqtmain_qgis_after_meta.yaml", "3.18.3"),
    ],
)
def test_qt_main(old_meta, new_meta, new_ver, tmpdir):
    with open(os.path.join(YAML_PATH, old_meta)) as fp:
        in_yaml = fp.read()

    if isinstance(new_meta, tuple):
        out_yamls = []

        for nm in new_meta:
            with open(os.path.join(YAML_PATH, nm)) as fp:
                out_yamls.append(fp.read())
    else:
        with open(os.path.join(YAML_PATH, new_meta)) as fp:
            out_yamls = [fp.read()]

    failed = []
    excepts = []
    for out_yaml in out_yamls:
        try:
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
        except Exception as e:
            failed.append(True)
            excepts.append(e)
        else:
            failed.append(False)
            excepts.append(None)

    if all(failed):
        for e in excepts:
            if e is not None:
                raise e

    assert not all(failed)
