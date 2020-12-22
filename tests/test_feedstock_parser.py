import os
import pprint

import pytest

from conda_forge_tick.feedstock_parser import _get_requirements
from conda_forge_tick.utils import parse_meta_yaml


@pytest.mark.parametrize("plat,arch,cfg,has_cudnn", [
        ("linux", "64", "linux_64_cuda_compiler_version10.2numpy1.19python3.9.____cpython.yaml", True),  # noqa
        ("osx", "64", "osx_64_numpy1.16python3.6.____cpython.yaml", False),
])
def test_parse_cudnn(plat, arch, cfg, has_cudnn):
    recipe_dir = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "pytorch-cpu-feedstock",
            "recipe",
        )
    )

    with open(os.path.join(recipe_dir, "meta.yaml"), "r") as fp:
        recipe_text = fp.read()

    meta = parse_meta_yaml(
        recipe_text,
        for_pinning=False,
        platform=plat,
        arch=arch,
        recipe_dir=recipe_dir,
        cbc_path=os.path.join(recipe_dir, "..", ".ci_support", cfg),
    )

    if has_cudnn:
        assert any(
            "cudnn" in out.get("requirements", {}).get("host", [])
            for out in meta["outputs"]
        ), pprint.pformat(meta)
    else:
        assert all(
            "cudnn" not in out.get("requirements", {}).get("host", [])
            for out in meta["outputs"]
        ), pprint.pformat(meta)


def test_get_requirements():
    meta_yaml = {
        "requirements": {"build": ["1", "2"], "host": ["2", "3"]},
        "outputs": [
            {"requirements": {"host": ["4"]}},
            {"requirements": {"run": ["5"]}},
            {"requirements": ["6"]},
        ],
    }
    assert _get_requirements({}) == set()
    assert _get_requirements(meta_yaml) == {"1", "2", "3", "4", "5", "6"}
    assert _get_requirements(meta_yaml, outputs=False) == {"1", "2", "3"}
    assert _get_requirements(meta_yaml, host=False) == {"1", "2", "5", "6"}
