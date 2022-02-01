import os
import tempfile
import copy

from grayskull.__main__ import create_python_recipe
from conda_forge_tick.audit import (
    extract_deps_from_source,
    compare_depfinder_audit,
)
from conda_forge_tick.feedstock_parser import load_feedstock
from conda_forge_tick.recipe_parser import CondaMetaYAML, CONDA_SELECTOR


def _merge_dep_comparisons_sec(dep_comparison, _dep_comparison):
    if dep_comparison and _dep_comparison:
        all_keys = set(dep_comparison) | set(_dep_comparison)
        for k in all_keys:
            v = dep_comparison.get(k, set())
            v_nms = {_v.split(" ")[0] for _v in v}
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


def merge_dep_comparisons(dep1, dep2):
    """Merge two dep comparison dicts.

    Parameters
    ----------
    dep1 : dict
        The first one to be merged. Keys in this one take precedence over
        keys in `dep2`.
    dep2 : dict
        The second one to be merged. Keys in this one are only added to `dep1`
        if the package name is not in `dep1`.

    Returns
    -------
    d : dict
        The merged dep comparison.
    """
    d = {}
    for section in ["host", "run"]:
        d[section] = _merge_dep_comparisons_sec(
            copy.deepcopy(dep1.get(section, {})),
            copy.deepcopy(dep2.get(section, {})),
        )
    return d


def make_grayskull_recipe(attrs):
    """Make a grayskull recipe given bot node attrs.

    Parameters
    ----------
    attrs : dict or LazyJson
        The node attrs.

    Returns
    -------
    recipe : str
        The generated grayskull recipe as a string.
    """
    pkg_version = attrs["version"]
    pkg_name = attrs["name"]
    recipe, _ = create_python_recipe(
        pkg_name=pkg_name,
        version=pkg_version,
        download=False,
        is_strict_cf=True,
        from_local_sdist=False,
    )

    with tempfile.TemporaryDirectory() as td:
        pth = os.path.join(td, "meta.yaml")
        recipe.save(pth)
        with open(pth) as f:
            out = f.read()
    return out


def get_grayskull_comparison(attrs):
    """Get the dependency comparison between the recipe and grayskull.

    Parameters
    ----------
    attrs : dict or LazyJson
        The bot node attrs.

    Returns
    -------
    d : dict
        The dependency comparison with conda-forge.
    """
    gs_recipe = make_grayskull_recipe(attrs)

    # load the feedstock with the grayskull meta_yaml
    new_attrs = load_feedstock(attrs.get("feedstock_name"), {}, meta_yaml=gs_recipe)
    d = {}
    for section in ["host", "run"]:
        gs_run = {c for c in new_attrs.get("total_requirements").get(section, set())}

        d[section] = {}
        cf_minus_df = {c for c in attrs.get("total_requirements").get(section, set())}
        df_minus_cf = set()
        for req in gs_run:
            if req in cf_minus_df:
                cf_minus_df = cf_minus_df - {req}
            else:
                df_minus_cf.add(req)

        d[section]["cf_minus_df"] = cf_minus_df
        d[section]["df_minus_cf"] = df_minus_cf

    return d, gs_recipe


def get_depfinder_comparison(recipe_dir, node_attrs, python_nodes):
    """Get the dependency comparison between the recipe and the source code.

    Parameters
    ----------
    recipe_dir : str
        The path to the recipe.
    node_attrs : dict or LazyJson
        The bot node attrs.
    python_nodes : set
        The set of nodes which are python packages. The comparison will be
        restricted to these nodes.

    Returns
    -------
    d : dict
        The dependency comparison with conda-forge.
    """
    deps = extract_deps_from_source(recipe_dir)
    return {
        "run": compare_depfinder_audit(
            deps,
            node_attrs,
            node_attrs["name"],
            python_nodes=python_nodes,
        ),
    }


def generate_dep_hint(dep_comparison, kind):
    """Generate a dep hint.

    Parameters
    ----------
    dep_comparison : dict
        The dependency comparison.
    kind : str
        The kind of comparison (e.g., source code, grayskull, etc.)

    Returns
    -------
    hint : str
        The dependency hint string.
    """
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

    df_cf = ""
    for sec in ["host", "run"]:
        for k in dep_comparison.get(sec, {}).get("df_minus_cf", set()):
            df_cf += f"- {k}" + "\n"
    cf_df = ""
    for sec in ["host", "run"]:
        for k in dep_comparison.get(sec, {}).get("cf_minus_df", set()):
            cf_df += f"- {k}" + "\n"

    if len(df_cf) > 0 or len(cf_df) > 0:
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
        hint += f"Analysis by {kind} shows **no discrepancy** with the stated requirements in the meta.yaml."  # noqa: E501
    return hint


def _ok_for_dep_updates(lines):
    is_multi_output = any(ln.lstrip().startswith("outputs:") for ln in lines)
    return not is_multi_output


def _update_sec_deps(recipe, dep_comparison, sections_to_update):
    updated_deps = False

    rqkeys = list(_gen_key_selector(recipe.meta, "requirements"))
    if len(rqkeys) == 0:
        recipe.meta["requirements"] = {}

    for rqkey in _gen_key_selector(recipe.meta, "requirements"):
        for section in ["host", "run"]:

            seckeys = list(_gen_key_selector(recipe.meta[rqkey], section))
            if len(seckeys) == 0:
                recipe.meta[rqkey][section] = []

            for seckey in _gen_key_selector(recipe.meta[rqkey], section):
                deps = sorted(
                    list(dep_comparison.get(section, {}).get("df_minus_cf", set())),
                )[::-1]
                for dep in deps:
                    dep_pkg_nm = dep.split(" ", 1)[0]

                    # do not replace pin compatible keys
                    if seckey.startswith("run") and any(
                        (
                            "pin_compatible" in rq
                            and ("'%s'" % dep_pkg_nm in rq or '"%s"' % dep_pkg_nm in rq)
                        )
                        for rq in recipe.meta[rqkey][seckey]
                    ):
                        continue

                    # find location of old dep
                    # add if not found, otherwise replace
                    loc = None
                    for i, rq in enumerate(recipe.meta[rqkey][seckey]):
                        pkg_nm = rq.split(" ", 1)[0]
                        if dep_pkg_nm == pkg_nm:
                            loc = i
                            break
                    if loc is None:
                        recipe.meta[rqkey][seckey].insert(0, dep)
                    else:
                        recipe.meta[rqkey][seckey][loc] = dep
                    updated_deps = True

    return updated_deps


def _gen_key_selector(dct, key):
    for k in dct:
        if k == key or (CONDA_SELECTOR in k and k.split(CONDA_SELECTOR)[0] == key):
            yield k


def apply_dep_update(recipe_dir, dep_comparison):
    """Upodate a recipe given a dependency comparison.

    Parameters
    ----------
    recipe_dir : str
        The path to the recipe dir.
    dep_comparison : dict
        The dependency comparison.

    Returns
    -------
    update_deps : bool
        True if deps were updated, False otherwise.
    """
    recipe_pth = os.path.join(recipe_dir, "meta.yaml")
    with open(recipe_pth) as fp:
        lines = fp.readlines()

    sections_to_update = ["host", "run"]
    if _ok_for_dep_updates(lines) and any(
        len(dep_comparison.get(s, {}).get("df_minus_cf", set())) > 0
        for s in sections_to_update
    ):
        recipe = CondaMetaYAML("".join(lines))
        updated_deps = _update_sec_deps(
            recipe,
            dep_comparison,
            sections_to_update,
        )
        if updated_deps:
            with open(recipe_pth, "w") as fp:
                recipe.dump(fp)
