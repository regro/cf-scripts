from conda_forge_tick.audit import (
    extract_deps_from_source,
    compare_depfinder_audit,
)


def merge_dep_comparisons(dep_comparison, _dep_comparison):
    if dep_comparison and _dep_comparison:
        all_keys = set(dep_comparison) | set(_dep_comparison)
        for k in all_keys:
            v = dep_comparison.get(k, set())
            v_nms = {
                _v.split(" ")[0] for _v in v
            }
            for _v in _dep_comparison.get(k, set()):
                _v_nm = _v.split(" ")[0]
                if _v_nm not in v_nms:
                    v.add(_v)
            if v:
                dep_comparison[k] = v

        return dep_comparison
    elif dep_comparison:
        return dep_comparison
    else:
        return _dep_comparison


def get_grayskull_comparison(recipe_dir, attrs):
    return {}, ""


def get_depfinder_comparison(recipe_dir, node_attrs, python_nodes):
    deps = extract_deps_from_source(recipe_dir)
    return compare_depfinder_audit(
        deps,
        node_attrs,
        node_attrs["name"],
        python_nodes=python_nodes,
    )


def generate_dep_hint(dep_comparison, kind):
    hint = "\n\nDependency Analysis\n--------------------\n\n"
    hint += (
        "Please note that this analysis is **highly experimental**. "
        "The aim here is to make maintenance easier by inspecting the package's dependencies. "  # noqa: E501
        "Importantly this analysis does not support optional dependencies, "
        "please double check those before making changes. "
        "If you do not want hinting of this kind ever please add "
        "`bot: inspection: false` to your `conda-forge.yml`. "
        "If you encounter issues with this feature please ping the bot team `conda-forge/bot`.\n\n"  # noqa: E501
    )
    if dep_comparison:
        df_cf = ""
        for k in dep_comparison.get("df_minus_cf", set()):
            df_cf += f"- {k}" + "\n"
        cf_df = ""
        for k in dep_comparison.get("cf_minus_df", set()):
            cf_df += f"- {k}" + "\n"
        hint += (
            f"Analysis by {kind} shows a discrepancy between it and the"
            " the package's stated requirements in the meta.yaml."
        )
        if df_cf:
            hint += (
                f"\n\n### Packages found by {kind} but not in the meta.yaml:\n"  # noqa: E501
                f"{df_cf}"
            )
        if cf_df:
            hint += (
                f"\n\n### Packages found in the meta.yaml but not found by {kind}:\n"  # noqa: E501
                f"{cf_df}"
            )
    else:
        hint += (
            f"Analysis by {kind} shows **no discrepancy** with the stated requirements in the meta.yaml."  # noqa: E501
        )
    return hint


def apply_grayskull_update(recipe_dir, gs_recipe):
    pass


def apply_depfinder_update(recipe_dir, dep_comparison):
    pass
