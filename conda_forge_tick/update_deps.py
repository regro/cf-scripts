import copy
import logging
import os
import pprint
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Literal, Union

import requests
from ruamel.yaml import YAML
from stdlib_list import stdlib_list

from conda_forge_tick.depfinder_api import simple_import_to_pkg_map
from conda_forge_tick.feedstock_parser import load_feedstock
from conda_forge_tick.make_graph import COMPILER_STUBS_WITH_STRONG_EXPORTS
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.provide_source_code import provide_source_code
from conda_forge_tick.pypi_name_mapping import _KNOWN_NAMESPACE_PACKAGES
from conda_forge_tick.recipe_parser import CONDA_SELECTOR, CondaMetaYAML
from conda_forge_tick.settings import settings

try:
    from grayskull.main import create_python_recipe
except ImportError:
    from grayskull.__main__ import create_python_recipe

logger = logging.getLogger(__name__)

yaml = YAML()
yaml.default_flow_style = False
yaml.block_seq_indent = True
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.width = 4096

EnvDepComparison = dict[Literal["df_minus_cf", "cf_minus_df"], set[str]]
DepComparison = dict[Literal["host", "run"], EnvDepComparison]


SECTIONS_TO_PARSE = ["host", "run"]
SECTIONS_TO_UPDATE = ["run"]

IGNORE_STUBS = ["doc", "example", "demo", "test", "unit_tests", "testing"]
IGNORE_TEMPLATES = ["*/{z}/*", "*/{z}s/*"]
DEPFINDER_IGNORE = []
for k in IGNORE_STUBS:
    for tmpl in IGNORE_TEMPLATES:
        DEPFINDER_IGNORE.append(tmpl.format(z=k))
DEPFINDER_IGNORE += [
    "*testdir/*",
    "*conftest*",
    "*/test.py",
    "*/versioneer.py",
    "*/run_test.py",
    "*/run_tests.py",
]

BUILTINS = set().union(
    # Some libs support older python versions, we don't want their std lib
    # entries in our diff though
    *[set(stdlib_list(k)) for k in ["2.7", "3.5", "3.6", "3.7", "3.8", "3.9"]]
)

STATIC_EXCLUDES = (
    {
        "python",
        "setuptools",
        "pip",
        "versioneer",
        # not a real dep
        "cross-python",
    }
    | BUILTINS
    | set(COMPILER_STUBS_WITH_STRONG_EXPORTS)
)

RANKINGS = []
for _ in range(10):
    r = requests.get(
        os.path.join(
            settings().graph_github_backend_raw_base_url,
            "ranked_hubs_authorities.json",
        )
    )
    if r.status_code == 200:
        RANKINGS = r.json()
        break
del r


def extract_deps_from_source(recipe_dir):
    with (
        provide_source_code(recipe_dir) as cb_work_dir,
        pushd(cb_work_dir),
    ):
        logger.debug("cb_work_dir: %s", cb_work_dir)
        logger.debug("BUILTINS: %s", BUILTINS)
        logger.debug("DEPFINDER_IGNORE: %s", DEPFINDER_IGNORE)

        pkg_map = simple_import_to_pkg_map(
            cb_work_dir,
            builtins=BUILTINS,
            ignore=DEPFINDER_IGNORE,
        )
        logger.debug("pkg_map: %s", pkg_map)
        return pkg_map


def compare_depfinder_audit(
    deps: Dict,
    attrs: Dict,
    node: str,
    python_nodes,
) -> Dict[str, set]:
    d = extract_missing_packages(
        required_packages=deps.get("required", {}),
        questionable_packages=deps.get("questionable", {}),
        run_packages=attrs["requirements"]["run"],
        node=node,
        python_nodes=python_nodes,
    )
    return d


def extract_missing_packages(
    required_packages,
    questionable_packages,
    run_packages,
    node,
    python_nodes,
):
    exclude_packages = STATIC_EXCLUDES.union(
        {node, node.replace("-", "_"), node.replace("_", "-")},
    )

    d = {}
    cf_minus_df = set(run_packages)
    df_minus_cf = set()
    for import_name, supplying_pkgs in required_packages.items():
        # If there is any overlap in the cf requirements and the supplying
        # pkgs remove from the cf_minus_df set
        overlap = supplying_pkgs & run_packages
        if overlap:
            # XXX: This is particularly annoying with clobbers
            cf_minus_df = cf_minus_df - overlap
        else:
            if "." in import_name:
                if any(import_name.startswith(k) for k in _KNOWN_NAMESPACE_PACKAGES):
                    for k in _KNOWN_NAMESPACE_PACKAGES:
                        if import_name.startswith(k):
                            subname = import_name[len(k) + 1 :].split(".")[0]
                            import_name = k + "." + subname
                            break
                else:
                    import_name = import_name.split(".")[0]

            if any(k == import_name for k in supplying_pkgs):
                pkg_name = import_name
            else:
                pkg_name = next(iter(k for k in RANKINGS if k in supplying_pkgs), None)
            if pkg_name:
                df_minus_cf.add(pkg_name)
            else:
                df_minus_cf.update(supplying_pkgs)

    for import_name, supplying_pkgs in questionable_packages.items():
        overlap = supplying_pkgs & run_packages
        if overlap:
            cf_minus_df = cf_minus_df - overlap

    # Only report for python nodes, we don't inspect for other deps
    if python_nodes:
        cf_minus_df = (cf_minus_df - exclude_packages) & python_nodes
    if cf_minus_df:
        d.update(cf_minus_df=cf_minus_df)

    df_minus_cf = df_minus_cf - exclude_packages
    if df_minus_cf:
        d.update(df_minus_cf=df_minus_cf)
    return d


def get_dep_updates_and_hints(
    update_deps: Union[str | Literal[False]],
    recipe_dir: str,
    attrs,
    python_nodes,
    version_key: str,
):
    """Get updated deps and hints.

    Parameters
    ----------
    update_deps : str | Literal[False]
        An update kind. See the code below for what is supported.
    recipe_dir : str
        The directory with the recipe.
    attrs : dict-like
        the bot node attrs for the feedstock.
    python_nodes : set-like
        A set of all bot python nodes.
    version_key : str
        The version key in the node attrs to use for grayskull.

    Returns
    -------
    dep_comparison : dict of dicts of sets
        A dictionary with the dep updates. See the hint generation code below
        to understand its contents.
    hint : str
        The dependency update hint.


    Raises
    ------
    ValueError
        If the update kind is not supported.
    """
    if update_deps == "disabled":
        # no dependency updates or hinting
        return {}, ""

    if update_deps in ["hint", "hint-source", "update-source"]:
        dep_comparison = get_depfinder_comparison(
            recipe_dir,
            attrs,
            python_nodes,
        )
        logger.info("source dep. comp: %s", pprint.pformat(dep_comparison))
        kind = "source code inspection"
        hint = generate_dep_hint(dep_comparison, kind)
        return dep_comparison, hint

    if update_deps in ["hint-grayskull", "update-grayskull"]:
        dep_comparison, _ = get_grayskull_comparison(
            attrs,
            version_key=version_key,
        )
        logger.info("grayskull dep. comp: %s", pprint.pformat(dep_comparison))
        kind = "grayskull"
        hint = generate_dep_hint(dep_comparison, kind)
        return dep_comparison, hint

    if update_deps in ["hint-all", "update-all"]:
        df_dep_comparison = get_depfinder_comparison(
            recipe_dir,
            attrs,
            python_nodes,
        )
        logger.info("source dep. comp: %s", pprint.pformat(df_dep_comparison))
        dep_comparison, _ = get_grayskull_comparison(
            attrs,
            version_key=version_key,
        )
        logger.info("grayskull dep. comp: %s", pprint.pformat(dep_comparison))
        dep_comparison = merge_dep_comparisons(
            copy.deepcopy(dep_comparison),
            copy.deepcopy(df_dep_comparison),
        )
        logger.info("combined dep. comp: %s", pprint.pformat(dep_comparison))
        kind = "source code inspection+grayskull"
        hint = generate_dep_hint(dep_comparison, kind)
        return dep_comparison, hint

    raise ValueError(f"update kind '{update_deps}' not supported.")


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
    for section in SECTIONS_TO_PARSE:
        d[section] = _merge_dep_comparisons_sec(
            copy.deepcopy(dep1.get(section, {})),
            copy.deepcopy(dep2.get(section, {})),
        )
    return d


def make_grayskull_recipe(attrs, version_key="version"):
    """Make a grayskull recipe given bot node attrs.

    Parameters
    ----------
    attrs : dict or LazyJson
        The node attrs.
    version_key : str, optional
        The version key to use from the attrs. Default is "version".

    Returns
    -------
    recipe : str
        The generated grayskull recipe as a string.
    """
    if version_key not in attrs:
        pkg_version = attrs.get("version_pr_info", {}).get(version_key)
    else:
        pkg_version = attrs[version_key]

    src = attrs["meta_yaml"].get("source", {}) or {}
    if isinstance(src, dict):
        src = [src]
    is_pypi = False
    is_github = False
    for s in src:
        if "url" in s:
            if any(
                pypi_slug in s["url"]
                for pypi_slug in [
                    "/pypi.io/",
                    "/pypi.org/",
                    "/pypi.python.org/",
                    "/files.pythonhosted.org/",
                ]
            ):
                is_pypi = True
                break

    if not is_pypi:
        for s in src:
            if "url" in s:
                if "github.com/" in s["url"]:
                    is_github = True
                    github_url = s["url"]
                    break
    # we don't know so assume pypi
    if not is_pypi and not is_github:
        is_pypi = True

    if is_pypi:
        pkg_name = attrs["name"]
    elif is_github:
        url_parts = github_url.split("/")
        if len(url_parts) < 5:
            logger.warning(
                "github url %s for grayskull dep update is too short! assuming pypi...",
                github_url,
            )
            pkg_name = attrs["name"]
        else:
            pkg_name = "/".join(url_parts[:5])

    is_noarch = "noarch: python" in attrs["raw_meta_yaml"]
    logger.info(
        "making grayskull recipe for pkg %s w/ version %s",
        pkg_name,
        pkg_version,
    )
    recipe, _ = create_python_recipe(
        pkg_name=pkg_name,
        version=pkg_version,
        download=False,
        is_strict_cf=True,
        from_local_sdist=False,
        is_arch=not is_noarch,
    )

    with tempfile.TemporaryDirectory() as td:
        pth = os.path.join(td, "meta.yaml")
        recipe.save(pth)
        with open(pth) as f:
            out = f.read()

    # code around a grayskull bug
    # see https://github.com/conda-incubator/grayskull/issues/295
    if "[py>=40]" in out:
        out = out.replace("[py>=40]", "[py>=400]")

    logger.info("grayskull recipe:\n%s", out)

    return out


def get_grayskull_comparison(attrs, version_key="version"):
    """Get the dependency comparison between the recipe and grayskull.

    Parameters
    ----------
    attrs : dict or LazyJson
        The bot node attrs.
    version_key : str, optional
        The version key to use from the attrs. Default is "version".

    Returns
    -------
    d : dict
        The dependency comparison with conda-forge.
    """
    gs_recipe = make_grayskull_recipe(attrs, version_key=version_key)

    # load the feedstock with the grayskull meta_yaml
    new_attrs = load_feedstock(attrs.get("feedstock_name"), {}, meta_yaml=gs_recipe)
    d = {}
    for section in SECTIONS_TO_PARSE:
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
    logger.debug('recipe_dir: "%s"', recipe_dir)
    p = Path(recipe_dir)
    logger.debug("listing contents of %s", str(p))
    for item in p.iterdir():
        logger.debug("%s", str(item))
    deps = extract_deps_from_source(recipe_dir)
    logger.debug("deps from source: %s", deps)
    df_audit = compare_depfinder_audit(
        deps,
        node_attrs,
        node_attrs["name"],
        python_nodes=python_nodes,
    )
    logger.debug("depfinder audit: %s", df_audit)
    return {"run": df_audit}


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
        "`bot: inspection: disabled` to your `conda-forge.yml`. "
        "If you encounter issues with this feature please ping the bot team `conda-forge/bot`.\n\n"  # noqa: E501
    )

    df_cf = ""
    for sec in SECTIONS_TO_PARSE:
        for k in dep_comparison.get(sec, {}).get("df_minus_cf", set()):
            df_cf += f"- {k}" + "\n"
    cf_df = ""
    for sec in SECTIONS_TO_PARSE:
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


def _update_sec_deps(recipe, dep_comparison, sections_to_update, update_python=False):
    updated_deps = False

    rqkeys = list(_gen_key_selector(recipe.meta, "requirements"))
    if len(rqkeys) == 0:
        recipe.meta["requirements"] = {}

    for rqkey in _gen_key_selector(recipe.meta, "requirements"):
        for section in sections_to_update:
            seckeys = list(_gen_key_selector(recipe.meta[rqkey], section))
            if len(seckeys) == 0:
                recipe.meta[rqkey][section] = []

            for seckey in _gen_key_selector(recipe.meta[rqkey], section):
                deps = sorted(
                    list(dep_comparison.get(section, {}).get("df_minus_cf", set())),
                )[::-1]
                for dep in deps:
                    dep_pkg_nm = dep.split(" ", 1)[0]

                    # do not touch python itself - to finicky
                    if dep_pkg_nm == "python" and not update_python:
                        continue

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


@dataclass
class Patch:
    before: str | None = None
    after: str | None = None


def _env_dep_comparison_to_patches(
    env_dep_comparison: EnvDepComparison,
) -> dict[str, Patch]:
    deps_to_remove = copy.copy(env_dep_comparison["cf_minus_df"])
    deps_to_add = copy.copy(env_dep_comparison["df_minus_cf"])
    patches: dict[str, Patch] = {}
    for dep in deps_to_add:
        package = dep.split(" ")[0]
        patches[package] = Patch(after=dep)
    for dep in deps_to_remove:
        package = dep.split(" ")[0]
        if package in patches:
            patches[package].before = dep
        else:
            patches[package] = Patch(before=dep)
    return patches


def _apply_env_dep_comparison(
    deps: list[str], env_dep_comparison: EnvDepComparison
) -> list[str]:
    new_deps = copy.copy(deps)
    patches = _env_dep_comparison_to_patches(env_dep_comparison)
    for package, patch in patches.items():
        # Do not touch Python itself - too finicky.
        if package == "python":
            continue
        if patch.before is None:
            new_deps.append(patch.after)
        elif patch.after is None:
            new_deps.remove(patch.before)
        else:
            new_deps[new_deps.index(patch.before)] = patch.after
    return new_deps


def _is_multi_output_v1_recipe(recipe: dict) -> bool:
    return "outputs" in recipe


def _is_v1_recipe_okay_for_dep_updates(recipe: dict) -> bool:
    return not _is_multi_output_v1_recipe(recipe=recipe)


def _apply_dep_update_v1(recipe: dict, dep_comparison: DepComparison) -> dict:
    new_recipe = copy.deepcopy(recipe)
    if not _is_v1_recipe_okay_for_dep_updates(recipe):
        return new_recipe

    host_deps = _apply_env_dep_comparison(
        recipe["requirements"]["host"], dep_comparison["host"]
    )
    run_deps = _apply_env_dep_comparison(
        recipe["requirements"]["run"], dep_comparison["run"]
    )
    new_recipe["requirements"]["host"] = host_deps
    new_recipe["requirements"]["run"] = run_deps
    return new_recipe


def apply_dep_update(recipe_dir, dep_comparison):
    """Update a recipe given a dependency comparison.

    Parameters
    ----------
    recipe_dir : str
        The path to the recipe dir.
    dep_comparison : dict
        The dependency comparison.
    """
    if (recipe_file := Path(recipe_dir).joinpath("recipe.yaml")).is_file():
        recipe = yaml.load(recipe_file.read_text())
        if (new_recipe := _apply_dep_update_v1(recipe, dep_comparison)) != recipe:
            with recipe_file.open("w") as f:
                yaml.dump(new_recipe, f)
        return
    recipe_pth = os.path.join(recipe_dir, "meta.yaml")
    with open(recipe_pth) as fp:
        lines = fp.readlines()

    if _ok_for_dep_updates(lines) and any(
        len(dep_comparison.get(s, {}).get("df_minus_cf", set())) > 0
        for s in SECTIONS_TO_UPDATE
    ):
        recipe = CondaMetaYAML("".join(lines))
        updated_deps = _update_sec_deps(
            recipe,
            dep_comparison,
            SECTIONS_TO_UPDATE,
        )
        # updated_deps is True if deps were updated, False otherwise.
        if updated_deps:
            with open(recipe_pth, "w") as fp:
                recipe.dump(fp)
