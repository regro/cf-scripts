import os

import pytest
from flaky import flaky
from test_migrators import run_test_migration

from conda_forge_tick.migrators import JpegTurboMigrator, Version

JPEGJPEGTURBO = JpegTurboMigrator()
VERSION_WITH_JPEGTURBO = Version(
    set(),
    piggy_back_migrations=[JPEGJPEGTURBO],
)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


@flaky
@pytest.mark.parametrize(
    "old_meta,new_meta,new_ver",
    [
        (
            "jpegturbo_pillow_before_meta.yaml",
            "jpegturbo_pillow_after_meta.yaml",
            "9.4.0",
        ),
    ],
)
def test_jpeg_turbo(old_meta, new_meta, new_ver, tmpdir):
    with open(os.path.join(YAML_PATH, old_meta)) as fp:
        in_yaml = fp.read()

    with open(os.path.join(YAML_PATH, new_meta)) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_WITH_JPEGTURBO,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": VERSION_WITH_JPEGTURBO.migrator_version,
            "version": new_ver,
        },
        tmpdir=tmpdir,
        should_filter=False,
    )
