import os
import pytest
from flaky import flaky

from conda_forge_tick.migrators import LibboostMigrator, Version
from test_migrators import run_test_migration


TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


LIBBOOST = LibboostMigrator()
VERSION_WITH_LIBBOOST = Version(
    set(),
    piggy_back_migrations=[LIBBOOST],
)


@pytest.mark.parametrize(
    "feedstock,new_ver",
    [
        # single output; no run-dep
        ("gudhi", "1.10.0"),
        # single output; with run-dep
        ("carve", "1.10.0"),
        # multiple outputs, many don't depend on boost; comment trickiness
        ("fenics", "1.10.0"),
        # multiple outputs, jinja-style pinning
        ("poppler", "1.10.0"),
        # multiple outputs, complicated selector & pinning combinations
        ("scipopt", "1.10.0"),
        # testing boost -> libboost-python
        ("rdkit", "1.10.0"),
        # interaction between boost & boost-cpp;
        # multiple outputs but no host deps
        ("cctx", "1.10.0"),
    ],
)
def test_boost(feedstock, new_ver, tmpdir):
    before = f"libboost_{feedstock}_before_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, before)) as fp:
        in_yaml = fp.read()

    after = f"libboost_{feedstock}_after_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, after)) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_WITH_LIBBOOST,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": VERSION_WITH_LIBBOOST.migrator_version,
            "version": new_ver,
        },
        tmpdir=tmpdir,
        should_filter=False,
    )
