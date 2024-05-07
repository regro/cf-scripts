import os
import re

import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import StdlibMigrator, Version

TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


STDLIB = StdlibMigrator()
VERSION_WITH_STDLIB = Version(
    set(),
    piggy_back_migrations=[STDLIB],
)


@pytest.mark.parametrize(
    "feedstock,new_ver,expect_cbc",
    [
        # package with many outputs, includes inheritance from global build env
        ("arrow", "1.10.0", False),
        # package without c compiler, but with selectors
        ("daal4py", "1.10.0", False),
        # problems with spurious selectors applied to stdlib
        ("fenics", "1.10.0", False),
        # package involving selectors and m2w64_c compilers, and compilers in
        # unusual places (e.g. in host & run sections)
        ("go", "1.10.0", True),
        # test that pure metapackages don't get stdlib added
        ("htcondor", "1.10.0", True),
        # package that got failed to get stdlib added
        ("mgis", "1.10.0", False),
        # package that reuses feedstock-name; sole global build section
        ("pagmo", "1.10.0", False),
        # package with rust compilers
        ("polars", "1.10.0", False),
        # package that intentionally reuses feedstock-name for output
        ("rdkit", "1.10.0", False),
        # package without compilers, but with sysroot_linux-64
        ("sinabs", "1.10.0", True),
        # test that we skip recipes that already contain a {{ stdlib("c") }}
        ("skip_migration", "1.10.0", False),
        # no-op on noatrch: python recipe
        ("rucio-clients", "34.3.0", False),
        # test recipe with templated name
        ("gz-common", "5_5.6.0", False),
        # test recipe with quoting
        ("libhdbpp-timescale", "2.1.0", False),
    ],
)
def test_stdlib(feedstock, new_ver, expect_cbc, tmpdir):
    before = f"stdlib_{feedstock}_before_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, before)) as fp:
        in_yaml = fp.read()

    after = f"stdlib_{feedstock}_after_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, after)) as fp:
        out_yaml = fp.read()

    recipe_dir = os.path.join(tmpdir, f"{feedstock}-feedstock")
    os.makedirs(recipe_dir, exist_ok=True)

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
        tmpdir=recipe_dir,
        should_filter=False,
    )

    cbc_pth = os.path.join(recipe_dir, "conda_build_config.yaml")
    if expect_cbc:
        with open(cbc_pth) as fp:
            lines = fp.readlines()
        assert any(re.match(r"c_stdlib_version:\s+\#\s\[linux\]", x) for x in lines)
