import os
import tempfile

from conda_forge_tick.utils import load
from conda_forge_tick.recipe_parser import CondaMetaYAML
from conda_forge_tick.update_deps import (
    get_depfinder_comparison,
    get_grayskull_comparison,
    generate_dep_hint,
    make_grayskull_recipe,
    _update_sec_deps,
    _merge_dep_comparisons_sec,
)

import pytest


@pytest.mark.parametrize(
    "dp1,dp2,m",
    [
        ({}, {}, {}),
        (
            {"df_minus_cf": {"a"}},
            {},
            {"df_minus_cf": {"a"}},
        ),
        (
            {},
            {"df_minus_cf": {"a"}},
            {"df_minus_cf": {"a"}},
        ),
        (
            {"df_minus_cf": {"a"}},
            {"cf_minus_df": {"b"}},
            {"df_minus_cf": {"a"}, "cf_minus_df": {"b"}},
        ),
        (
            {"df_minus_cf": {"a"}},
            {"df_minus_cf": {"c", "d"}, "cf_minus_df": {"b"}},
            {"df_minus_cf": {"a", "c", "d"}, "cf_minus_df": {"b"}},
        ),
        (
            {"df_minus_cf": {"c", "d"}, "cf_minus_df": {"b"}},
            {"df_minus_cf": {"a"}},
            {"df_minus_cf": {"a", "c", "d"}, "cf_minus_df": {"b"}},
        ),
        (
            {"df_minus_cf": {"a >=2"}},
            {"df_minus_cf": {"a"}},
            {"df_minus_cf": {"a >=2"}},
        ),
        (
            {"df_minus_cf": {"a"}},
            {"df_minus_cf": {"a >=2"}},
            {"df_minus_cf": {"a"}},
        ),
    ],
)
def test_merge_dep_comparisons(dp1, dp2, m):
    assert m == _merge_dep_comparisons_sec(dp1, dp2)


def test_generate_dep_hint():
    hint = generate_dep_hint({}, "blahblahblah")
    assert "no discrepancy" in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" not in hint
    assert "but not in the meta.yaml" not in hint

    df = {"df_minus_cf": {"a"}, "cf_minus_df": {"b"}}
    hint = generate_dep_hint(df, "blahblahblah")
    assert "no discrepancy" not in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" in hint
    assert "but not in the meta.yaml" in hint

    df = {"df_minus_cf": {"a"}}
    hint = generate_dep_hint(df, "blahblahblah")
    assert "no discrepancy" not in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" not in hint
    assert "but not in the meta.yaml" in hint

    df = {"cf_minus_df": {"b"}}
    hint = generate_dep_hint(df, "blahblahblah")
    assert "no discrepancy" not in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" in hint
    assert "but not in the meta.yaml" not in hint


def test_make_grayskull_recipe():
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    recipe = make_grayskull_recipe(attrs)
    assert recipe != ""


def test_get_grayskull_comparison():
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    d, rs = get_grayskull_comparison(attrs)
    assert rs != ""
    assert d["run"]["cf_minus_df"] == {"python <3.9"}
    assert any(_d.startswith("python") for _d in d["run"]["df_minus_cf"])


def test_update_run_deps():
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    d, rs = get_grayskull_comparison(attrs)
    lines = attrs["raw_meta_yaml"].splitlines()
    lines = [ln + "\n" for ln in lines]
    recipe = CondaMetaYAML("".join(lines))

    updated_deps = _update_sec_deps(recipe, d, ["host", "run"])
    print("\n" + recipe.dumps())
    assert updated_deps
    assert "python >=3.6" in recipe.dumps()


def test_get_depfinder_comparison():
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)

    with tempfile.TemporaryDirectory() as tmpdir:
        pth = os.path.join(tmpdir, "meta.yaml")
        with open(pth, "w") as fp:
            fp.write(attrs["raw_meta_yaml"])

        d = get_depfinder_comparison(tmpdir, attrs, {"conda"})
    assert len(d["run"]["df_minus_cf"]) > 0
    assert "host" not in d
