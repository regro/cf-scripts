import os
import pytest

from conda_forge_tick.migrators import MatplotlibBase
from test_migrators import run_test_migration

MPLB = MatplotlibBase(
    old_pkg="matplotlib",
    new_pkg="matplotlib-base",
    rationale=(
        "Unless you need `pyqt`, recipes should depend only on " "`matplotlib-base`."
    ),
    pr_limit=5,
)


YAML_PATH = os.path.join(os.path.dirname(__file__), 'test_yaml')


@pytest.mark.parametrize('existing_yums', [
    tuple(),
    ('blah',),
    ('blah', 'xorg-x11-server-Xorg'),
    ('xorg-x11-server-Xorg',)
])
def test_matplotlib_base(existing_yums, tmpdir):
    with open(os.path.join(YAML_PATH, 'mplb.yaml'), 'r') as fp:
        in_yaml = fp.read()

    with open(
            os.path.join(YAML_PATH, 'mplb_correct.yaml'),
            'r',
    ) as fp:
        out_yaml = fp.read()

    yum_pth = os.path.join(tmpdir, 'yum_requirements.txt')

    if len(existing_yums) > 0:
        with open(yum_pth, 'w') as fp:
            for yum in existing_yums:
                fp.write('%s\n' % yum)

    run_test_migration(
        m=MPLB,
        inp=in_yaml,
        output=out_yaml,
        kwargs={},
        prb="I noticed that this recipe depends on `matplotlib` instead of ",
        mr_out={
            "migrator_name": "MatplotlibBase",
            "migrator_version": MPLB.migrator_version,
            "name": "matplotlib-to-matplotlib-base",
        },
        tmpdir=tmpdir,
    )

    with open(yum_pth, 'r') as fp:
        yums = fp.readlines()

    yums = set([y.strip() for y in yums])
    assert 'xorg-x11-server-Xorg' in yums
    for y in existing_yums:
        assert y in yums
