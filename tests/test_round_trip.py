import tempfile
import textwrap

from conda_forge_tick.migrators.round_trip import YAMLRoundTrip


def test_round_trip_v0():
    myaml = textwrap.dedent(
        """\
        blah: &foo # [unix]
        - blah  # [osx]
        - foo
        foo: *foo
        """
    )
    fmyaml = textwrap.dedent(
        """\
        blah:   # [unix]
          - blah # [osx]
          - foo
        foo:
          - blah # [osx]
          - foo
        """
    )

    with tempfile.TemporaryDirectory() as d:
        with open(f"{d}/meta.yaml", "w") as f:
            f.write(myaml)
        YAMLRoundTrip().migrate(d, {})
        with open(f"{d}/meta.yaml") as f:
            assert f.read() == fmyaml

    assert not YAMLRoundTrip().filter({"meta_yaml": {"schema_version": 0}})


def test_round_trip_v1():
    myaml = textwrap.dedent(
        """\
        blah:
        - blah # a dep
        - foo
        """
    )
    fmyaml = textwrap.dedent(
        """\
        blah:
          - blah # a dep
          - foo
        """
    )

    with tempfile.TemporaryDirectory() as d:
        with open(f"{d}/recipe.yaml", "w") as f:
            f.write(myaml)
        YAMLRoundTrip().migrate(d, {})
        with open(f"{d}/recipe.yaml") as f:
            assert f.read() == fmyaml

    assert not YAMLRoundTrip().filter({"meta_yaml": {"schema_version": 1}})
