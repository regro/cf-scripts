import os
import subprocess


def test_version(tmpdir, caplog, env_setup):
    from conda_forge_tick.xonsh_utils import indir
    import logging

    from conda_forge_tick.migrators import Version
    from conda_forge_tick.utils import populate_feedstock_attributes

    VERSION = Version(set(), dict(), dict())

    malicious_recipe = """\
    {% set version = "0" %}
    package:
      name: muah_ha_ha
      version: {{ version }}

    source:
      url: https://{{ os.environ["PASSWORD"][0] }}/{{ os.environ["PASSWORD"][1:] }}
      sha256: dca77e463c56d42bbf915197c9b95e98913c85bef150d2e1dd18626b8c2c9c32
    build:
      number: 0
      noarch: python
      script: python -m pip install --no-deps --ignore-installed .

    requirements:
      host:
        - python
        - pip
        - numpy
      run:
        - python
        - numpy
        - matplotlib
        - colorspacious

    test:
      imports:
        - viscm

    about:
      home: https://github.com/bids/viscm
      license: MIT
      license_family: MIT
      # license_file: '' we need to an issue upstream to get a license in the source dist.
      summary: A colormap tool

    extra:
      recipe-maintainers:
        - kthyng
        - {{ os.environ["PASSWORD"] }}
    """
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    in_yaml = malicious_recipe
    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    with open(os.path.join(tmpdir, "recipe", "meta.yaml"), "w") as f:
        f.write(in_yaml)
    with indir(tmpdir):
        subprocess.run(["git", "init"])

    pmy = populate_feedstock_attributes("blah", {}, in_yaml, "{}")
    # This url gets saved in https://github.com/regro/cf-graph-countyfair
    assert pmy["url"] != "https://u/npassword"
    pmy["new_version"] = "1"
    mr = VERSION.migrate(
        os.path.join(tmpdir, "recipe"),
        pmy,
        hash_type=pmy.get("hash_type", "sha256"),
    )
