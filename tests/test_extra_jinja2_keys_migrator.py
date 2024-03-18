import os

from flaky import flaky
from test_migrators import run_test_migration

from conda_forge_tick.migrators import ExtraJinja2KeysCleanup, Version

VERSION_CF = Version(
    set(),
    piggy_back_migrations=[ExtraJinja2KeysCleanup()],
)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


@flaky
def test_version_extra_jinja2_keys_cleanup(tmpdir):
    with open(os.path.join(YAML_PATH, "version_extra_jinja2_keys.yaml")) as fp:
        in_yaml = fp.read()

    with open(
        os.path.join(YAML_PATH, "version_extra_jinja2_keys_correct.yaml"),
    ) as fp:
        out_yaml = fp.read()

    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    run_test_migration(
        m=VERSION_CF,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": "0.20.0"},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": "0.20.0",
        },
        tmpdir=os.path.join(tmpdir, "recipe"),
    )
