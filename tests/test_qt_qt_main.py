import os
import pytest

from conda_forge_tick.migrators import QtQtMainMigrator
from test_migrators import run_test_migration

QTQTMAIN = QtQtMainMigrator()

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


@pytest.mark.parametrize(
    "old_meta,new_meta",
    [
        ("qtqtmain_octave_before_meta.yaml", "qtqtmain_octave_after_meta.yaml"),
        ("qtqtmain_qgis_before_meta.yaml", "qtqtmain_qgis_after_meta.yaml"),
        ("qtqtmain_opencv_before_meta.yaml", "qtqtmain_opencv_after_meta.yaml"),
    ],
)
def test_matplotlib_base(old_meta, new_meta, tmpdir):
    with open(os.path.join(YAML_PATH, old_meta)) as fp:
        in_yaml = fp.read()

    with open(os.path.join(YAML_PATH, new_meta)) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=QTQTMAIN,
        inp=in_yaml,
        output=out_yaml,
        kwargs={},
        prb="I noticed that this recipe depends on `qt` instead of ",
        mr_out={
            "migrator_name": "QtQtMainMigrator",
            "migrator_version": QTQTMAIN.migrator_version,
            "name": "qt-to-qt-main",
        },
        tmpdir=tmpdir,
    )
