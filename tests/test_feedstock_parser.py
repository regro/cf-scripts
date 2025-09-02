import pprint
from pathlib import Path

import pytest

from conda_forge_tick.feedstock_parser import _get_requirements, load_feedstock_local
from conda_forge_tick.utils import parse_meta_yaml, parse_recipe_yaml


@pytest.mark.parametrize(
    "plat,arch,cfg,has_cudnn",
    [
        (
            "linux",
            "64",
            "linux_64_cuda_compiler_version10.2numpy1.19python3.9.____cpython.yaml",
            True,
        ),
        ("osx", "64", "osx_64_numpy1.16python3.6.____cpython.yaml", False),
    ],
)
def test_parse_cudnn(plat, arch, cfg, has_cudnn):
    recipe_dir = Path(__file__).parent.joinpath(
        "pytorch-cpu-feedstock", "meta_yaml", "recipe"
    )

    recipe_text = recipe_dir.joinpath("meta.yaml").read_text()

    meta = parse_meta_yaml(
        recipe_text,
        for_pinning=False,
        platform=plat,
        arch=arch,
        cbc_path=str(recipe_dir.joinpath("..", ".ci_support", cfg)),
        log_debug=True,
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


@pytest.mark.parametrize(
    "plat,cfg,has_cudnn",
    [
        (
            "linux-64",
            "linux_64_cuda_compiler_version10.2numpy1.19python3.9.____cpython.yaml",
            True,
        ),
        ("osx-64", "osx_64_numpy1.16python3.6.____cpython.yaml", False),
    ],
)
def test_parse_cudnn_recipe_yaml(plat, cfg, has_cudnn):
    recipe_dir = Path(__file__).parent.joinpath(
        "pytorch-cpu-feedstock", "recipe_yaml", "recipe"
    )
    recipe_text = recipe_dir.joinpath("recipe.yaml").read_text()

    parsed_recipe = parse_recipe_yaml(
        recipe_text,
        for_pinning=False,
        platform_arch=plat,
        cbc_path=str(recipe_dir.joinpath("..", ".ci_support", cfg)),
    )

    if has_cudnn:
        assert any(
            "cudnn" in out.get("requirements", {}).get("host", [])
            for out in parsed_recipe["outputs"]
        ), pprint.pformat(parsed_recipe)
    else:
        assert all(
            "cudnn" not in out.get("requirements", {}).get("host", [])
            for out in parsed_recipe["outputs"]
        ), pprint.pformat(parsed_recipe)


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


def test_feedstock_parser_load_feedstock_local_semi_ate_stdf():
    attrs = load_feedstock_local(
        "semi-ate-stdf",
        {},
    )
    assert attrs["feedstock_name"] == "semi-ate-stdf"
    assert "parsing_error" in attrs


def test_feedstock_parser_load_feedstock_local_fenics_basix_version():
    attrs = load_feedstock_local(
        "fenics-basix",
        {},
    )
    assert attrs["feedstock_name"] == "fenics-basix"
    assert attrs["version"] == attrs["meta_yaml"]["outputs"][0]["version"]
    assert attrs["name"] == attrs["meta_yaml"]["outputs"][0]["name"]
    assert attrs["name"] == "fenics-basix"
