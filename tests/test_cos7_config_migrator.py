import os

import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import Cos7Config, Version
from conda_forge_tick.migrators.cos7 import REQUIRED_RE_LINES, _has_line_set

VERSION_COS7 = Version(
    set(),
    piggy_back_migrations=[Cos7Config()],
)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


@pytest.mark.parametrize("remove_quay", [False, True])
@pytest.mark.parametrize("case", list(range(len(REQUIRED_RE_LINES))))
def test_version_cos7_config(case, remove_quay, tmpdir):
    with open(os.path.join(YAML_PATH, "version_cos7_config_simple.yaml")) as fp:
        in_yaml = fp.read()

    with open(
        os.path.join(YAML_PATH, "version_cos7_config_simple_correct.yaml"),
    ) as fp:
        out_yaml = fp.read()

    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    cfg = os.path.join(tmpdir, "recipe", "conda_build_config.yaml")

    with open(cfg, "w") as fp:
        for i, (_, _, first, second) in enumerate(REQUIRED_RE_LINES):
            if i != case:
                fp.write(first + "\n")
                if "docker_image" in first and remove_quay:
                    fp.write(
                        second.replace("quay.io/condaforge/", "condaforge/") + "\n",
                    )

    run_test_migration(
        m=VERSION_COS7,
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
    with open(cfg) as fp:
        cfg_lines = fp.readlines()

    for first_re, second_re, first, second in REQUIRED_RE_LINES:
        assert _has_line_set(cfg_lines, first_re, second_re), (first, second)


@pytest.mark.parametrize("case", list(range(len(REQUIRED_RE_LINES))))
def test_version_cos7_config_skip(case, tmpdir):
    with open(os.path.join(YAML_PATH, "version_cos7_config_simple.yaml")) as fp:
        in_yaml = fp.read()

    with open(
        os.path.join(YAML_PATH, "version_cos7_config_simple_correct.yaml"),
    ) as fp:
        out_yaml = fp.read()

    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    cfg = os.path.join(tmpdir, "recipe", "conda_build_config.yaml")

    with open(cfg, "w") as fp:
        for i, (_, _, first, second) in enumerate(REQUIRED_RE_LINES):
            if i != case:
                fp.write(first + "blarg\n")
                fp.write(second + "blarg\n")

    run_test_migration(
        m=VERSION_COS7,
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
    with open(cfg) as fp:
        cfg_lines = fp.readlines()

    for i, (first_re, second_re, first, second) in enumerate(REQUIRED_RE_LINES):
        if i != case:
            assert _has_line_set(cfg_lines, first_re, second_re), (first, second)
