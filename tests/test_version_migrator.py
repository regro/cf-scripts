import os
import logging
import pytest
from flaky import flaky

from conda_forge_tick.migrators import Version

from test_migrators import run_test_migration

VERSION = Version(set())

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


@pytest.mark.parametrize(
    "case,new_ver",
    [
        ("faiss-split", "1.7.3"),
        ("docker-py", "6.0.1"),
        ("allennlp", "2.10.1"),
        ("numpy", "1.24.0"),
        ("dbt", "1.2.0"),
        ("jinja2expr", "1.1.1"),
        ("weird", "1.6.0"),
        ("compress", "0.9"),
        ("onesrc", "2.4.1"),
        ("multisrc", "2.4.1"),
        ("jinja2sha", "2.4.1"),
        ("r", "1.3_2"),
        ("multisrclist", "2.25.0"),
        ("jinja2selsha", "4.7.2"),
        ("jinja2nameshasel", "4.7.2"),
        ("shaquotes", "0.6.0"),
        ("cdiff", "0.15.0"),
        ("selshaurl", "3.7.0"),
        ("buildbumpmpi", "7.8.0"),
        ("multisrclistnoup", "3.11.3"),
        ("pypiurl", "0.7.1"),
        ("githuburl", "1.1.0"),
        ("ccacheerr", "3.7.7"),
        ("cranmirror", "0.3.3"),
        ("sha1", "5.0.1"),
        ("icu", "68.1"),
        ("libevent", "2.1.12"),
        ("boost", "1.74.0"),
        ("boostcpp", "1.74.0"),
        ("python", "3.9.5"),
        # upstream is not available
        # ("mumps", "5.2.1"),
        # ("cb3multi", "6.0.0"),
    ],
)
@flaky
def test_version(case, new_ver, tmpdir, caplog):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    with open(os.path.join(YAML_PATH, "version_%s.yaml" % case)) as fp:
        in_yaml = fp.read()

    with open(os.path.join(YAML_PATH, "version_%s_correct.yaml" % case)) as fp:
        out_yaml = fp.read()

    kwargs = {"new_version": new_ver}
    if case == "sha1":
        kwargs["hash_type"] = "sha1"

    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yaml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmpdir=tmpdir,
    )


@pytest.mark.parametrize(
    "case,new_ver",
    [
        ("badvernoup", "10.12.0"),
        ("selshaurlnoup", "3.8.0"),
        ("missingjinja2noup", "7.8.0"),
        ("nouphasurl", "3.11.3"),
        ("giturl", "7.0"),
    ],
)
def test_version_noup(case, new_ver, tmpdir, caplog):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    with open(os.path.join(YAML_PATH, "version_%s.yaml" % case)) as fp:
        in_yaml = fp.read()

    with open(os.path.join(YAML_PATH, "version_%s_correct.yaml" % case)) as fp:
        out_yaml = fp.read()

    attrs = run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={},
        tmpdir=tmpdir,
    )

    print("\n\n" + attrs["new_version_errors"][new_ver] + "\n\n")


def test_version_cupy(tmpdir, caplog):
    case = "cupy"
    new_ver = "8.5.0"
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    with open(os.path.join(YAML_PATH, "version_%s.yaml" % case)) as fp:
        in_yaml = fp.read()

    with open(os.path.join(YAML_PATH, "version_%s_correct.yaml" % case)) as fp:
        out_yaml = fp.read()

    kwargs = {"new_version": new_ver}
    if case == "sha1":
        kwargs["hash_type"] = "sha1"

    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yaml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": "Version",
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmpdir=tmpdir,
    )
