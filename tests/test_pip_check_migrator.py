import os
import pytest

from conda_forge_tick.migrators import (
    Version,
    PipCheckMigrator,
)

from test_migrators import run_test_migration

PC = PipCheckMigrator()
VERSION_PC = Version(piggy_back_migrations=[PC])

YAML_PATH = os.path.join(os.path.dirname(__file__), 'test_yaml')


@pytest.mark.parametrize(
    'case',
    ['simple', 'selector', 'selector_partial'])
def test_version_pipcheck(case, tmpdir):
    with open(os.path.join(YAML_PATH, 'version_pipcheck_%s.yaml' % case), 'r') as fp:
        in_yaml = fp.read()

    with open(
            os.path.join(YAML_PATH, 'version_pipcheck_%s_correct.yaml' % case),
            'r',
    ) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_PC,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmpdir=tmpdir,
    )


def test_version_pipcheck_outputs(tmpdir):
    with open(os.path.join(YAML_PATH, 'version_pipcheck_outputs.yaml'), 'r') as fp:
        in_yaml = fp.read()

    with open(
            os.path.join(YAML_PATH, 'version_pipcheck_outputs_correct.yaml'),
            'r',
    ) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_PC,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "1.1.0"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "1.1.0",
        },
        tmpdir=tmpdir,
    )
