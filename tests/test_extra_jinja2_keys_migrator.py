import os
from ruamel.yaml import YAML

from conda_forge_tick.migrators import (
    Version,
    ExtraJinja2KeysCleanup,
)

from test_migrators import run_test_migration

VERSION_CF = Version(piggy_back_migrations=[ExtraJinja2KeysCleanup()], check_solvability=False)

YAML_PATH = os.path.join(os.path.dirname(__file__), 'test_yaml')


def test_version_extra_jinja2_keys_cleanup(tmpdir):
    with open(os.path.join(YAML_PATH, 'version_extra_jinja2_keys.yaml'), 'r') as fp:
        in_yaml = fp.read()

    with open(
            os.path.join(YAML_PATH, 'version_extra_jinja2_keys_correct.yaml'),
            'r',
    ) as fp:
        out_yaml = fp.read()

    os.makedirs(os.path.join(tmpdir, 'recipe'), exist_ok=True)
    run_test_migration(
        m=VERSION_CF,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.20.0"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": "0.20.0",
        },
        tmpdir=os.path.join(tmpdir, 'recipe'),
    )
