from pathlib import Path

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import MiniReplacement, Version

XZLIBLZMADEVEL = MiniReplacement(old_pkg="xz", new_pkg="liblzma-devel")
JPEGJPEGTURBO = MiniReplacement(old_pkg="jpeg", new_pkg="libjpeg-turbo")
QTQTMAIN = MiniReplacement(old_pkg="qt", new_pkg="qt-main")

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}

VERSION_WITH_XZLIBLZMADEVEL = Version(
    set(),
    piggy_back_migrations=[XZLIBLZMADEVEL],
    total_graph=TOTAL_GRAPH,
)
VERSION_WITH_JPEGTURBO = Version(
    set(),
    piggy_back_migrations=[JPEGJPEGTURBO],
    total_graph=TOTAL_GRAPH,
)
VERSION_WITH_QTQTMAIN = Version(
    set(),
    piggy_back_migrations=[QTQTMAIN],
    total_graph=TOTAL_GRAPH,
)

YAML_PATHS = [
    Path(__file__).parent / "test_yaml",
    Path(__file__).parent / "test_v1_yaml",
]


@pytest.mark.parametrize(
    "old_meta,new_meta,new_ver,migrator",
    [
        (
            "libtiff_with_xz.yaml",
            "libtiff_with_liblzma_devel.yaml",
            "4.7.0",
            VERSION_WITH_XZLIBLZMADEVEL,
        ),
        (
            "jpegturbo_pillow_before_meta.yaml",
            "jpegturbo_pillow_after_meta.yaml",
            "9.4.0",
            VERSION_WITH_JPEGTURBO,
        ),
        pytest.param(
            "qtqtmain_octave_before_meta.yaml",
            ("qtqtmain_octave_after_meta.yaml", "qtqtmain_octave_xz_after_meta.yaml"),
            "2025.3.75",
            VERSION_WITH_QTQTMAIN,
            marks=pytest.mark.xfail(reason="qgis URLs do not always work!"),
        ),
        pytest.param(
            "qtqtmain_qgis_before_meta.yaml",
            "qtqtmain_qgis_after_meta.yaml",
            "3.18.3",
            VERSION_WITH_QTQTMAIN,
            marks=pytest.mark.xfail(reason="qgis URLs do not always work!"),
        ),
    ],
)
@pytest.mark.parametrize("recipe_version", [0, 1])
def test_liblzma_devel(old_meta, new_meta, new_ver, migrator, recipe_version, tmp_path):
    if not isinstance(new_meta, tuple):
        new_meta = (new_meta,)

    out_yamls = []
    for nm in new_meta:
        out_yamls.append(YAML_PATHS[recipe_version].joinpath(nm).read_text())

    failed = []
    excepts = []
    for out_yaml in out_yamls:
        try:
            run_test_migration(
                m=migrator,
                inp=YAML_PATHS[recipe_version].joinpath(old_meta).read_text(),
                output=out_yaml,
                kwargs={"new_version": new_ver},
                prb="Dependencies have been updated if changed",
                mr_out={
                    "migrator_name": Version.name,
                    "migrator_version": migrator.migrator_version,
                    "version": new_ver,
                },
                tmp_path=tmp_path,
                should_filter=False,
                recipe_version=recipe_version,
            )
        except Exception as e:
            failed.append(True)
            excepts.append(e)
        else:
            failed.append(False)
            excepts.append(None)

    if all(failed):
        for e in excepts:
            if e is not None:
                raise e

    assert not all(failed)
