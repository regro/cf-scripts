import os
import pytest
from ruamel.yaml import YAML

from conda_forge_tick.migrators import (
    Version,
    ExtraJinja2KeysCleanup,
)

from test_migrators import run_test_migration

VERSION_CF = Version(piggy_back_migrations=[ExtraJinja2KeysCleanup()])

YAML_PATH = os.path.join(os.path.dirname(__file__), 'test_yaml')


print("Importing!")
@pytest.mark.parametrize('cases', [
    tuple(),
    # ('min_r_ver',),
])
def test_version_extra_jinja2_keys_cleanup(cases, tmpdir):
    yaml = YAML()

    with open(os.path.join(YAML_PATH, 'version_extra_jinja2_keys.yaml'), 'r') as fp:
        in_yaml = fp.read()

    with open(
            os.path.join(YAML_PATH, 'version_extra_jinja2_keys_correct.yaml'),
            'r',
    ) as fp:
        out_yaml = fp.read()

    cf_yml = {}
    print("############ cases: ", cases)
    for case in cases:
        cf_yml[case] = '10'
    cf_yml['foo'] = 'bar'

    os.makedirs(os.path.join(tmpdir, 'recipe'), exist_ok=True)
    cf_yml_pth = os.path.join(tmpdir, 'conda-forge.yml')
    with open(cf_yml_pth, 'w') as fp:
        yaml.dump(cf_yml, fp)

    print("Before run_test_migration")
    run_test_migration(
        m=VERSION_CF,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.19.2"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "0.19.2",
        },
        tmpdir=os.path.join(tmpdir, 'recipe'),
    )
    print("After run_test_migration")

    with open(cf_yml_pth, 'r') as fp:
        new_cf_yml = yaml.load(fp)

    assert 'min_r_ver' not in new_cf_yml
    assert 'min_py_ver' not in new_cf_yml
    assert 'max_r_ver' not in new_cf_yml
    assert 'max_py_ver' not in new_cf_yml
    assert 'compiler_stack' not in new_cf_yml
    assert cf_yml['foo'] == 'bar'
