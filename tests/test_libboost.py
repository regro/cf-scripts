import os

import networkx as nx
import pytest
from test_migrators import run_test_migration

from conda_forge_tick.migrators import LibboostMigrator, Version
from conda_forge_tick.migrators.libboost import _slice_into_output_sections

TEST_YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")


TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
LIBBOOST = LibboostMigrator()
VERSION_WITH_LIBBOOST = Version(
    set(),
    piggy_back_migrations=[LIBBOOST],
    total_graph=TOTAL_GRAPH,
)


@pytest.mark.parametrize(
    "feedstock,new_ver",
    [
        # single output; no run-dep
        ("gudhi", "1.10.0"),
        # single output; with run-dep
        ("carve", "1.10.0"),
        # multiple output; no run-dep
        ("arrow", "1.10.0"),
        # multiple outputs, many don't depend on boost; comment trickiness
        ("fenics", "1.10.0"),
        # multiple outputs, jinja-style pinning
        ("poppler", "1.10.0"),
        # multiple outputs, complicated selector & pinning combinations
        ("scipopt", "1.10.0"),
        # testing boost -> libboost-python
        ("rdkit", "1.10.0"),
        # interaction between boost & boost-cpp;
        # multiple outputs but no host deps
        ("cctx", "1.10.0"),
    ],
)
def test_boost(feedstock, new_ver, tmp_path):
    before = f"libboost_{feedstock}_before_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, before)) as fp:
        in_yaml = fp.read()

    after = f"libboost_{feedstock}_after_meta.yaml"
    with open(os.path.join(TEST_YAML_PATH, after)) as fp:
        out_yaml = fp.read()

    run_test_migration(
        m=VERSION_WITH_LIBBOOST,
        inp=in_yaml,
        output=out_yaml,
        kwargs={"new_version": new_ver},
        prb="Dependencies have been updated if changed",
        mr_out={
            "migrator_name": Version.name,
            "migrator_version": VERSION_WITH_LIBBOOST.migrator_version,
            "version": new_ver,
        },
        tmp_path=tmp_path,
        should_filter=False,
    )


def test_slice_into_output_sections_multioutput():
    lines = """\
package:
  name: blah
  version: 1.0.0

requirements:
  host:
    - foo

outputs:
  # comment
    - name: blarg  # comment
      requirements:
        host:
          - bar
    {{% jinja %}}

    {{% jinja %}}
    - name: blarg-jinja
      requirements:
        host:
          - baz
    {{% jinja %}}
    - requirements:
        host:
          - baz
      name: blarg2
  {{% jinja %}}

about:
  home: http://example.com
  license: MIT
  license_file:
    - file1
    - file2
"""
    sections = _slice_into_output_sections(
        lines.splitlines(),
        {
            "meta_yaml": {
                "outputs": [
                    {"name": "blarg"},
                    {"name": "blarg-jinja"},
                    {"name": "blarg2"},
                ]
            }
        },
    )
    assert len(sections) == 4
    assert (
        sections[-1]
        == """\
package:
  name: blah
  version: 1.0.0

requirements:
  host:
    - foo

outputs:
  # comment
""".splitlines()
    )
    assert (
        sections[0]
        == """\
    - name: blarg  # comment
      requirements:
        host:
          - bar
    {{% jinja %}}

    {{% jinja %}}""".splitlines()
    )
    assert (
        sections[1]
        == """\
    - name: blarg-jinja
      requirements:
        host:
          - baz
    {{% jinja %}}""".splitlines()
    )
    assert (
        sections[2]
        == """\
    - requirements:
        host:
          - baz
      name: blarg2
  {{% jinja %}}

about:
  home: http://example.com
  license: MIT
  license_file:
    - file1
    - file2""".splitlines()
    )


def test_slice_into_output_sections_global_only():
    lines = """\
package:
  name: blah
  version: 1.0.0

requirements:
  host:
    - foo

about:
  home: http://example.com
  license: MIT
  license_file:
    - file1
    - file2
"""
    sections = _slice_into_output_sections(
        lines.splitlines(),
        {"meta_yaml": {}},
    )
    assert len(sections) == 1
    assert sections[-1] == lines.splitlines()
