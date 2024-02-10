import os

import pytest
from flaky import flaky
from test_migrators import run_test_migration

from conda_forge_tick.migrators import StdlibMigrator, Version

TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


STDLIB = StdlibMigrator()
VERSION_WITH_STDLIB = Version(
    set(),
    piggy_back_migrations=[STDLIB],
)


@pytest.mark.parametrize(
    "feedstock,new_ver",
    [
        # package with many outputs, includes inheritance from global build env
        ("arrow", "1.10.0"),
        # package involving selectors and m2w64_c compilers, and compilers in
        # unusual places (e.g. in host & run sections)
        ("go", "1.10.0"),
        # package with rust compilers
        ("polars", "1.10.0"),
        # test that we skip recipes that already contain a {{ stdlib("c") }}
        ("skip_migration", "1.10.0"),
    ],
)
def test_stdlib(feedstock, new_ver, tmpdir):
    before = f"stdlib_{feedstock}_before_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, before)) as fp:
        in_yaml = fp.read()

    after = f"stdlib_{feedstock}_after_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, after)) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_WITH_STDLIB,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": VERSION_WITH_STDLIB.migrator_version,
            "version": new_ver,
        },
        tmpdir=tmpdir,
        should_filter=False,
    )
