import os

import pytest
from ruamel.yaml import YAML
from test_migrators import run_test_migration

from conda_forge_tick.migrators import CondaForgeYAMLCleanup, Version

VERSION_CF = Version(
    set(),
    piggy_back_migrations=[CondaForgeYAMLCleanup()],
)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


@pytest.mark.parametrize(
    "cases",
    [
        tuple(),
        ("min_r_ver",),
        ("min_py_ver",),
        ("max_r_ver",),
        ("max_py_ver",),
        ("max_r_ver", "max_py_ver"),
        ("compiler_stack", "max_r_ver"),
        ("compiler_stack"),
    ],
)
def test_version_cfyaml_cleanup(cases, tmpdir):
    yaml = YAML()

    with open(os.path.join(YAML_PATH, "version_cfyaml_cleanup_simple.yaml")) as fp:
        in_yaml = fp.read()

    with open(
        os.path.join(YAML_PATH, "version_cfyaml_cleanup_simple_correct.yaml"),
    ) as fp:
        out_yaml = fp.read()

    cf_yml = {}
    for case in cases:
        cf_yml[case] = "10"
    cf_yml["foo"] = "bar"

    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    cf_yml_pth = os.path.join(tmpdir, "conda-forge.yml")
    with open(cf_yml_pth, "w") as fp:
        yaml.dump(cf_yml, fp)

    run_test_migration(
        m=VERSION_CF,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmpdir=os.path.join(tmpdir, "recipe"),
    )

    with open(cf_yml_pth) as fp:
        new_cf_yml = yaml.load(fp)

    assert "min_r_ver" not in new_cf_yml
    assert "min_py_ver" not in new_cf_yml
    assert "max_r_ver" not in new_cf_yml
    assert "max_py_ver" not in new_cf_yml
    assert "compiler_stack" not in new_cf_yml
    assert cf_yml["foo"] == "bar"
