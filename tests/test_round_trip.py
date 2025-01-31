import tempfile

from conda_forge_tick.migrators.round_trip import YAMLRoundTrip


def test_round_trip_v0():
    myaml = """\
blah:  # [unix]
- blah  # [osx]
- foo
"""

    fmyaml = """\
blah:   # [unix]
  - blah # [osx]
  - foo
"""

    with tempfile.TemporaryDirectory() as d:
        with open(f"{d}/meta.yaml", "w") as f:
            f.write(myaml)
        YAMLRoundTrip().migrate(d, {})
        with open(f"{d}/meta.yaml") as f:
            assert f.read() == fmyaml


def test_round_trip_v1():
    myaml = """\
blah:
- blah # a dep
- foo
"""

    fmyaml = """\
blah:
  - blah # a dep
  - foo
"""

    with tempfile.TemporaryDirectory() as d:
        with open(f"{d}/recipe.yaml", "w") as f:
            f.write(myaml)
        YAMLRoundTrip().migrate(d, {})
        with open(f"{d}/recipe.yaml") as f:
            assert f.read() == fmyaml
