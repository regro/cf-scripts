import os
import pytest
from ruamel.yaml import YAML

from conda_forge_tick.migrators import (
    Version,
    MaxVerMigrator,
)

from test_migrators import run_test_migration

VERSION_MV = Version(piggy_back_migrations=[MaxVerMigrator()])

YAML_PATH = os.path.join(os.path.dirname(__file__), 'test_yaml')


@pytest.mark.parametrize('cases', [
    tuple(),
    ('r',),
    ('py',),
    ('r', 'py')
])
def test_version_maxver(cases, tmpdir):
    yaml = YAML()

    with open(os.path.join(YAML_PATH, 'version_maxver_simple.yaml'), 'r') as fp:
        in_yaml = fp.read()

    with open(
            os.path.join(YAML_PATH, 'version_maxver_simple_correct.yaml'),
            'r',
    ) as fp:
        out_yaml = fp.read()

    cf_yml = {}
    for case in cases:
        cf_yml['max_%s_ver' % case] = '10'
    cf_yml['foo'] = 'bar'

    os.makedirs(os.path.join(tmpdir, 'recipe'), exist_ok=True)
    cf_yml_pth = os.path.join(tmpdir, 'conda-forge.yml')
    with open(cf_yml_pth, 'w') as fp:
        yaml.dump(cf_yml, fp)

    run_test_migration(
        m=VERSION_MV,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.9"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "0.9",
        },
        tmpdir=os.path.join(tmpdir, 'recipe'),
    )

    with open(cf_yml_pth, 'r') as fp:
        new_cf_yml = yaml.load(fp)

    assert 'max_r_ver' not in new_cf_yml
    assert 'max_py_ver' not in new_cf_yml
    assert cf_yml['foo'] == 'bar'
