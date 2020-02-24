import os
import logging
import pytest

from conda_forge_tick.migrators import Version

from test_migrators import run_test_migration

VERSION = Version()

YAML_PATH = os.path.join(os.path.dirname(__file__), 'test_yaml')


@pytest.mark.parametrize('case,new_ver', [
    ('compress', '0.9'),
    ('onesrc', '2.4.1'),
    ('multisrc', '2.4.1'),
    ('jinja2sha', '2.4.1'),
    ('r', '1.3_2'),
    ('cb3multi', '6.0.0'),
    ('multisrclist', '2.25.0'),
    ('jinja2selsha', '4.7.2'),
    ('jinja2nameshasel', '4.7.2'),
    ('shaquotes', '0.6.0'),
    ('cdiff', '0.15.0'),
    ('selshaurl', '3.8.0'),
    ('buildbumpmpi', '7.8.0'),
    ('multisrclistnoup', '3.11.3'),
    ('pypiurl', '0.7.1'),
    ('githuburl', '1.1.0'),
])
def test_version(case, new_ver, tmpdir, caplog):
    caplog.set_level(
        logging.DEBUG,
        logger='conda_forge_tick.migrators.version',
    )

    with open(os.path.join(YAML_PATH, 'version_%s.yaml' % case), 'r') as fp:
        in_yaml = fp.read()

    with open(
            os.path.join(YAML_PATH, 'version_%s_correct.yaml' % case),
            'r',
    ) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmpdir=tmpdir,
    )


@pytest.mark.parametrize('case,new_ver', [
    ('badvernoup', '10.12.0'),
    ('selshaurlnoup', '3.8.0'),
    ('missingjinja2noup', '7.8.0'),
    ('nouphasurl', '3.11.3'),
])
def test_version_noup(case, new_ver, tmpdir, caplog):
    caplog.set_level(
        logging.DEBUG,
        logger='conda_forge_tick.migrators.version',
    )

    with open(os.path.join(YAML_PATH, 'version_%s.yaml' % case), 'r') as fp:
        in_yaml = fp.read()

    with open(
            os.path.join(YAML_PATH, 'version_%s_correct.yaml' % case),
            'r',
    ) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={},
        tmpdir=tmpdir,
    )
