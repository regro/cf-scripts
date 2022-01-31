from conda_forge_tick.update_deps import (
    get_depfinder_comparison,
    get_grayskull_comparison,
    generate_dep_hint,
    merge_dep_comparisons,
    apply_depfinder_update,
    apply_grayskull_update,
)

import pytest


@pytest.mark.parametrize("dp1,dp2,m", [
    ({}, {}, {}),
    (
        {"df_minus_cf": set(["a"])},
        {},
        {"df_minus_cf": set(["a"])},
    ),
    (
        {},
        {"df_minus_cf": set(["a"])},
        {"df_minus_cf": set(["a"])},
    ),
    (
        {"df_minus_cf": set(["a"])},
        {"cf_minus_df": set(["b"])},
        {"df_minus_cf": set(["a"]), "cf_minus_df": set(["b"])},
    ),
    (
        {"df_minus_cf": set(["a"])},
        {"df_minus_cf": set(["c", "d"]), "cf_minus_df": set(["b"])},
        {"df_minus_cf": set(["a", "c", "d"]), "cf_minus_df": set(["b"])},
    ),
    (
        {"df_minus_cf": set(["c", "d"]), "cf_minus_df": set(["b"])},
        {"df_minus_cf": set(["a"])},
        {"df_minus_cf": set(["a", "c", "d"]), "cf_minus_df": set(["b"])},
    ),
    (
        {"df_minus_cf": set(["a >=2"])},
        {"df_minus_cf": set(["a"])},
        {"df_minus_cf": set(["a >=2"])},
    ),
    (
        {"df_minus_cf": set(["a"])},
        {"df_minus_cf": set(["a >=2"])},
        {"df_minus_cf": set(["a"])},
    ),
])
def test_merge_dep_comparisons(dp1, dp2, m):
    assert m == merge_dep_comparisons(dp1, dp2)


def test_generate_dep_hint():
    hint = generate_dep_hint({}, "blahblahblah")
    assert "no discrepancy" in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" not in hint
    assert "but not in the meta.yaml" not in hint

    df = {"df_minus_cf": set(["a"]), "cf_minus_df": set(["b"])}
    hint = generate_dep_hint(df, "blahblahblah")
    assert "no discrepancy" not in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" in hint
    assert "but not in the meta.yaml" in hint

    df = {"df_minus_cf": set(["a"])}
    hint = generate_dep_hint(df, "blahblahblah")
    assert "no discrepancy" not in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" not in hint
    assert "but not in the meta.yaml" in hint

    df = {"cf_minus_df": set(["b"])}
    hint = generate_dep_hint(df, "blahblahblah")
    assert "no discrepancy" not in hint
    assert "blahblahblah" in hint
    assert "but not found by blahblahblah" in hint
    assert "but not in the meta.yaml" not in hint
