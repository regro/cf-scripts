import logging
import os
import random
from pathlib import Path

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import Version
from conda_forge_tick.migrators.version import VersionMigrationError

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
VERSION = Version(set(), total_graph=TOTAL_GRAPH)

YAML_PATH = Path(__file__).parent / "test_yaml"
YAML_V1_PATH = Path(__file__).parent / "test_v1_yaml"

VARIANT_SOURCES_NOT_IMPLEMENTED = (
    "Sources that depend on conda build config variants are not supported yet."
)


@pytest.mark.parametrize(
    "case,new_ver",
    [
        ("mpich", "4.1.1"),
        ("mpichv0", "4.1.0"),
        ("dash_extensions", "0.1.11"),
        ("numpy", "1.24.1"),
        ("python", "3.9.5"),
        ("faiss-split", "1.7.3"),
        ("docker-py", "6.0.1"),
        ("allennlp", "2.10.1"),
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
        ("event_stream", "1.6.3"),
        ("21cmfast", "3.4.0"),
        ("pyrsmq", "0.6.0"),
        ("quart_trio", "0.11.1"),
        ("reproc", "14.2.5"),
        ("riskfolio_lib", "6.3.1"),
        ("algotree", "0.7.3"),
        ("py_entitymatching", "0.4.2"),
        ("py_entitymatching_name", "0.4.2"),
        # these contain sources that depend on conda build config variants
        pytest.param(
            "polars_mixed_selectors",
            "1.1.0",
            marks=pytest.mark.xfail(reason=VARIANT_SOURCES_NOT_IMPLEMENTED),
        ),
        pytest.param(
            "polars_name_selectors",
            "1.1.0",
            marks=pytest.mark.xfail(reason=VARIANT_SOURCES_NOT_IMPLEMENTED),
        ),
        pytest.param(
            "polars_variant_selectors",
            "1.1.0",
            marks=pytest.mark.xfail(reason=VARIANT_SOURCES_NOT_IMPLEMENTED),
        ),
        # use conda build config variants directly to select source
        ("polars_by_variant", "1.20.0"),
        # upstream is not available
        # ("mumps", "5.2.1"),
        # ("cb3multi", "6.0.0"),
    ],
)
def test_version_up(case, new_ver, tmp_path, caplog):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    in_yaml = (YAML_PATH / f"version_{case}.yaml").read_text()
    out_yaml = (YAML_PATH / f"version_{case}_correct.yaml").read_text()

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
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
    )


@pytest.mark.parametrize(
    "case,new_ver",
    [
        ("pypi_url", "0.7.1"),
        ("jolt", "5.2.0"),
        ("build_number_via_context", "0.20.1"),
        ("build_as_expr", "3.6.2"),
        ("conditional_sources", "3.24.11"),
        ("cranmirror", "0.3.3"),
        ("event_stream", "1.6.3"),
        ("selshaurl", "3.7.0"),
        ("libssh", "0.11.1"),
        ("polars", "1.20.0"),
        ("svcore", "0.2025.40"),
    ],
)
def test_version_up_v1(case, new_ver, tmp_path, caplog):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    in_yaml = (YAML_V1_PATH / f"version_{case}.yaml").read_text()
    out_yaml = (YAML_V1_PATH / f"version_{case}_correct.yaml").read_text()

    try:
        conda_build_config = (
            YAML_V1_PATH / f"version_{case}_variants.yaml"
        ).read_text()
    except FileNotFoundError:
        conda_build_config = None

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
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
        recipe_version=1,
        conda_build_config=conda_build_config,
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
def test_version_noup(case, new_ver, tmp_path, caplog):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    with open(os.path.join(YAML_PATH, "version_%s.yaml" % case)) as fp:
        in_yaml = fp.read()

    with open(os.path.join(YAML_PATH, "version_%s_correct.yaml" % case)) as fp:
        out_yaml = fp.read()

    with pytest.raises(VersionMigrationError) as e:
        run_test_migration(
            m=VERSION,
            inp=in_yaml,
            output=out_yaml,
            kwargs={"new_version": new_ver},
            prb="Dependencies have been updated if changed",
            mr_out={},
            tmp_path=tmp_path,
        )

    assert "The recipe did not change in the version migration," in str(e.value), (
        e.value
    )


def test_version_cupy(tmp_path, caplog):
    case = "cupy"
    new_ver = "8.5.0"
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    in_yaml = Path(YAML_PATH).joinpath(f"version_{case}.yaml").read_text()
    out_yaml = Path(YAML_PATH).joinpath(f"version_{case}_correct.yaml").read_text()

    kwargs = {"new_version": new_ver}

    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yaml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
    )


def test_version_rand_frac(tmp_path, caplog):
    case = "aws_sdk_cpp"
    new_ver = "1.11.132"
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    random.seed(a=new_ver)
    urand = random.uniform(0, 1)
    assert urand < 0.1

    with open(os.path.join(YAML_PATH, "version_%s.yaml" % case)) as fp:
        in_yaml = fp.read()

    with open(os.path.join(YAML_PATH, "version_%s_correct.yaml" % case)) as fp:
        out_yaml = fp.read()

    kwargs = {"new_version": new_ver}
    kwargs["conda-forge.yml"] = {
        "bot": {"version_updates": {"random_fraction_to_keep": 0.1}},
    }
    run_test_migration(
        m=VERSION,
        inp=in_yaml,
        output=out_yaml,
        kwargs=kwargs,
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": Version.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
    )
    assert "random_fraction_to_keep: 0.1" in caplog.text
