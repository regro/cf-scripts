import os
import pytest
from ruamel.yaml import YAML

from conda_forge_tick.migrators import (
    Version,
    MPIPinRunAsBuildCleanup,
)
from conda_forge_tick.migrators.mpi_pin_run_as_build import MPIS
from test_migrators import run_test_migration

VERSION_CF = Version(
    set(),
    piggy_back_migrations=[MPIPinRunAsBuildCleanup()],
)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


@pytest.mark.parametrize(
    "vals",
    [
        {},
        {"mpich": "x.x"},
        {"openmpi": "x.x"},
        {"openmpi": "x.x", "mpich": "x.x"},
        {"blah": "x"},
        {"mpich": "x.x", "blah": "x"},
        {"openmpi": "x.x", "blah": "x"},
        {"openmpi": "x.x", "mpich": "x.x", "blah": "x"},
    ],
)
def test_version_mpi_pin_run_as_build_cleanup(vals, tmpdir):
    yaml = YAML()

    with open(os.path.join(YAML_PATH, "version_mprab_cleanup_simple.yaml")) as fp:
        in_yaml = fp.read()

    with open(
        os.path.join(YAML_PATH, "version_mprab_cleanup_simple_correct.yaml"),
    ) as fp:
        out_yaml = fp.read()

    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    cbc_pth = os.path.join(tmpdir, "recipe", "conda_build_config.yaml")
    cbc = {"pin_run_as_build": vals}
    with open(cbc_pth, "w") as fp:
        yaml.dump(cbc, fp)

    run_test_migration(
        m=VERSION_CF,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmpdir=os.path.join(tmpdir, "recipe"),
    )

    if len(vals) == 0 or "blah" not in cbc["pin_run_as_build"]:
        assert not os.path.exists(cbc_pth)
    else:
        with open(cbc_pth) as fp:
            new_cbc = yaml.load(fp)

        if "blah" in vals:
            assert "blah" in new_cbc["pin_run_as_build"]

        for mpi in MPIS:
            assert mpi not in new_cbc["pin_run_as_build"]
