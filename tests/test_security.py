import os
import subprocess


def test_env_is_protected_against_malicious_recipes(tmpdir, caplog, env_setup):
    import logging

    from conda_forge_tick.feedstock_parser import populate_feedstock_attributes
    from conda_forge_tick.os_utils import pushd

    malicious_recipe = """\
    {% set version = "0" %}
    package:
      name: muah_ha_ha
      version: {{ version }}

    source:
      url:
        - https://{{ os.environ["BOT_TOKEN"][0] }}/{{ os.environ["BOT_TOKEN"][1:] }}
        - {{ os.environ['pwd'] }}
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
        - {{ os.environ["BOT_TOKEN"] }}
    """  # noqa
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    in_yaml = malicious_recipe
    os.makedirs(os.path.join(tmpdir, "recipe"), exist_ok=True)
    with open(os.path.join(tmpdir, "recipe", "meta.yaml"), "w") as f:
        f.write(in_yaml)
    with pushd(tmpdir):
        subprocess.run(["git", "init"])

    pmy = populate_feedstock_attributes("blah", {}, in_yaml, None, "{}")

    # This url gets saved in https://github.com/regro/cf-graph-countyfair
    pswd = os.environ.get("TEST_BOT_TOKEN_VAL", "unpassword")
    tst_url = f"https://{pswd[0]}/{pswd[1:]}"
    assert pmy["url"][0] != tst_url
    assert pmy["url"][1] is None
