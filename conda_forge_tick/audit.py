"""Audit the dependencies of the conda-forge ecosystem"""
import os
import shutil
import tempfile
import time
import traceback
from collections import defaultdict
from concurrent.futures._base import as_completed
from typing import Dict

import networkx as nx
from stdlib_list import stdlib_list

from conda_forge_tick.make_graph import COMPILER_STUBS_WITH_STRONG_EXPORTS
from depfinder.main import (
    simple_import_to_pkg_map,
)
from depfinder import __version__ as depfinder_version
from grayskull.__main__ import create_python_recipe
from grayskull import __version__ as grayskull_version
import pandas as pd

from conda_forge_tick.contexts import MigratorSessionContext, FeedstockContext
from conda_forge_tick.git_utils import feedstock_url, fetch_repo
from conda_forge_tick.utils import (
    load_graph,
    dump,
    load,
    executor,
    _get_source_code,
    yaml_safe_load,
)
from conda_forge_tick.feedstock_parser import load_feedstock
from conda_forge_tick.xonsh_utils import indir, env

RUNTIME_MINUTES = 45

IGNORE_STUBS = ["doc", "example", "demo", "test", "unit_tests", "testing"]
IGNORE_TEMPLATES = ["*/{z}/*", "*/{z}s/*"]
DEPFINDER_IGNORE = []
for k in IGNORE_STUBS:
    for tmpl in IGNORE_TEMPLATES:
        DEPFINDER_IGNORE.append(tmpl.format(z=k))
DEPFINDER_IGNORE += ["*testdir/*", "*conftest*", "*/test.py", "*/versioneer.py"]

BUILTINS = set().union(
    # Some libs support older python versions, we don't want their std lib
    # entries in our diff though
    *[set(stdlib_list(k)) for k in ["2.7", "3.5", "3.6", "3.7"]]
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


PREFERRED_IMPORT_BY_PACKAGE_MAP = {
    "numpy": "numpy",
    "matplotlib-base": "matplotlib",
    "theano": "theano",
    "tensorflow-estimator": "tensorflow_estimator",
    "skorch": "skorch",
}

IMPORTS_BY_PACKAGE_OVERRIDE = {
    k: {v} for k, v in PREFERRED_IMPORT_BY_PACKAGE_MAP.items()
}
PACKAGES_BY_IMPORT_OVERRIDE = {
    v: {k} for k, v in PREFERRED_IMPORT_BY_PACKAGE_MAP.items()
}


def extract_deps_from_source(recipe_dir):
    cb_work_dir = _get_source_code(recipe_dir)
    with indir(cb_work_dir):
        return simple_import_to_pkg_map(
            cb_work_dir,
            builtins=BUILTINS,
            ignore=DEPFINDER_IGNORE,
        )


def depfinder_audit_feedstock(fctx: FeedstockContext, ctx: MigratorSessionContext):
    """Uses Depfinder to audit the imports for a python package"""
    # get feedstock
    feedstock_dir = os.path.join(ctx.rever_dir, fctx.feedstock_name + "-feedstock")
    origin = feedstock_url(fctx=fctx, protocol="https")
    fetch_repo(
        feedstock_dir=feedstock_dir,
        origin=origin,
        upstream=origin,
        branch=fctx.default_branch,
    )
    recipe_dir = os.path.join(feedstock_dir, "recipe")

    return extract_deps_from_source(recipe_dir)


def grayskull_audit_feedstock(fctx: FeedstockContext, ctx: MigratorSessionContext):
    """Uses grayskull to audit the requirements for a python package"""
    # TODO: come back to this, since CF <-> PyPI is not one-to-one and onto
    pkg_version = fctx.attrs["version"]
    pkg_name = fctx.package_name
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


AUDIT_REGISTRY = {
    "depfinder": {
        "run": depfinder_audit_feedstock,
        "writer": dump,
        "ext": "json",
        "version": depfinder_version,
        "creation_version": "4",
    },
    # Grayskull produces a valid meta.yaml, there is no in memory representation
    # for that so we just write out the string
    #    "grayskull": {
    #        "run": grayskull_audit_feedstock,
    #        "writer": lambda x, f: f.write(x),
    #        "dumper": yaml.dump,
    #        "ext": "yml",
    #        "version": grayskull_version,
    #        "creation_version": "1",
    #    },
}


def inner_grayskull_comparison(meta_yaml, attrs, node):
    # load the feedstock with the grayskull meta_yaml
    try:
        new_attrs = load_feedstock(node, {}, meta_yaml=meta_yaml)
    except Exception as e:
        return str(e)
    requirement_keys = [
        k
        for k in new_attrs
        if "requirements" in k and k not in {"requirements", "total_requirements"}
    ]
    results = defaultdict(dict)
    for k in requirement_keys:
        for kk in attrs[k]:
            cf_attrs_k_kk = attrs[k][kk]
            gs_attrs_k_kk = new_attrs[k][kk]
            if cf_attrs_k_kk != gs_attrs_k_kk and (
                kk != "test" and gs_attrs_k_kk != set("pip")
            ):
                results[k][kk] = {"cf": cf_attrs_k_kk, "grayskull": gs_attrs_k_kk}
                cf_minus_gs = cf_attrs_k_kk - gs_attrs_k_kk
                gs_minus_cf = gs_attrs_k_kk - cf_attrs_k_kk
                if cf_minus_gs:
                    results[k][kk].update({"cf_not_gs_diff": cf_minus_gs})
                if gs_minus_cf:
                    results[k][kk].update({"gs_not_cf_diff": gs_minus_cf})
    return dict(results) or False


def compare_grayskull_audits(gx):
    grayskull_files = os.listdir("audits/grayskull")
    bad_inspections = {}

    if "_net_audit.json" in grayskull_files:
        grayskull_files.pop(grayskull_files.index("_net_audit.json"))
        with open("audits/grayskull/_net_audit.json") as f:
            bad_inspections = load(f)

    futures = {}
    with executor("dask", max_workers=20) as pool:

        for node, attrs in gx.nodes("payload"):
            if not attrs.get("version"):
                continue
            node_version = f"{node}_{attrs['version']}"
            if node_version in bad_inspections:
                continue
            # construct the expected filename
            expected_filename = f"{node_version}.yml"
            if expected_filename in grayskull_files:
                with open(
                    os.path.join("audits/grayskull", expected_filename),
                ) as f:
                    meta_yaml = f.read()
                futures[
                    pool.submit(
                        inner_grayskull_comparison,
                        meta_yaml=meta_yaml,
                        attrs=attrs,
                        node=node,
                    )
                ] = node_version
        for future in as_completed(futures):
            try:
                bad_inspections[futures[future]] = future.result()
            except Exception as e:
                bad_inspections[futures[future]] = str(e)

    with open("audits/grayskull/_net_audit.json", "w") as f:
        dump(bad_inspections, f)
    return bad_inspections


try:
    RANKINGS = load(open("ranked_hubs_authorities.json"))
except FileNotFoundError:
    RANKINGS = []


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
            # TODO: sort by the rankings
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
    cf_minus_df = (cf_minus_df - exclude_packages) & python_nodes
    if cf_minus_df:
        d.update(cf_minus_df=cf_minus_df)

    df_minus_cf = df_minus_cf - exclude_packages
    if df_minus_cf:
        d.update(df_minus_cf=df_minus_cf)
    return d


def create_package_import_maps(nodes, mapping_yaml="mappings/pypi/name_mapping.yaml"):
    raw_import_map = yaml_safe_load(open(mapping_yaml))
    packages_by_import = defaultdict(set)
    imports_by_package = defaultdict(set)
    for item in raw_import_map:
        import_name = item["import_name"]
        conda_name = item["conda_name"]
        potential_conda_names = {
            conda_name,
            import_name,
            import_name.replace("_", "-"),
        } & nodes
        packages_by_import[import_name].update(potential_conda_names)
        imports_by_package[conda_name].update(
            [import_name, conda_name.replace("-", "_")],
        )
    imports_by_package.update(IMPORTS_BY_PACKAGE_OVERRIDE)
    packages_by_import.update(PACKAGES_BY_IMPORT_OVERRIDE)
    return imports_by_package, packages_by_import


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


def compare_depfinder_audits(gx):
    # This really needs to be all the python packages, since this doesn't cover outputs
    python_nodes = {n for n, v in gx.nodes("payload") if "python" in v.get("req", "")}
    python_nodes.update(
        [
            k
            for node_name, node in gx.nodes("payload")
            for k in node.get("outputs_names", [])
            if node_name in python_nodes
        ],
    )

    bad_inspection = {}
    files = os.listdir("audits/depfinder")

    if "_net_audit.json" in files:
        files.pop(files.index("_net_audit.json"))

    for node, attrs in gx.nodes("payload"):
        if (
            attrs.get("version", None) is None
            or attrs.get("archived", False)
            or attrs.get("bad", False)
        ):
            continue
        if "requirements" not in attrs:
            print("node %s doesn't have requirements!" % node, flush=True)
            continue

        node_version = f"{node}_{attrs['version']}"
        # construct the expected filename
        expected_filename = f"{node_version}.json"
        if expected_filename in files:
            with open(os.path.join("audits/depfinder", expected_filename)) as f:
                output = load(f)
            if isinstance(output, str) or "traceback" in output:
                bad_inspection[node_version] = output
                continue
            d = extract_missing_packages(
                required_packages=output.get("required", {}),
                questionable_packages=output.get("questionable", {}),
                run_packages=attrs["requirements"]["run"],
                node=node,
                python_nodes=python_nodes,
            )
            bad_inspection[node_version] = d or False
    with open("audits/depfinder/_net_audit.json", "w") as f:
        dump(bad_inspection, f)
    return bad_inspection


def compute_depfinder_accuracy(bad_inspection):
    count = {
        "time": time.time(),
        "accurate": 0,
        "cf_over_specified": 0,
        "cf_under_specified": 0,
        "cf_over_and_under_specified": 0,
        "errored": 0,
        "definder_version": depfinder_version,
        "audit_creation_version": AUDIT_REGISTRY["depfinder"]["creation_version"],
    }
    for k, v in bad_inspection.items():
        if not v:
            count["accurate"] += 1
        elif "cf_minus_df" in v and "df_minus_cf" in v:
            count["cf_over_and_under_specified"] += 1
        elif "df_minus_cf" in v:
            count["cf_under_specified"] += 1
        elif "cf_minus_df" in v:
            count["cf_over_specified"] += 1
        else:
            count["errored"] += 1
    df = pd.DataFrame.from_dict(count, orient="index").T
    df.to_csv(
        "audits/depfinder_accuracy.csv",
        mode="a",
        header=not os.path.exists("audits/depfinder_accuracy.csv"),
        index=False,
    )


def compute_grayskull_accuracy(bad_inspection):
    count = {
        "time": time.time(),
        "accurate": 0,
        "cf_over_specified": 0,
        "cf_under_specified": 0,
        "cf_over_and_under_specified": 0,
        "errored": 0,
        "grayskull_version": grayskull_version,
        "audit_creation_version": AUDIT_REGISTRY["grayskull"]["creation_version"],
    }
    for k, v in bad_inspection.items():
        if not v:
            count["accurate"] += 1
        elif "cf_not_gs_diff" in v and "gs_not_cf_diff" in v:
            count["cf_over_and_under_specified"] += 1
        elif "gs_not_cf_diff" in v:
            count["cf_under_specified"] += 1
        elif "cf_not_gs_diff" in v:
            count["cf_over_specified"] += 1
        else:
            count["errored"] += 1
    df = pd.DataFrame.from_dict(count, orient="index").T
    df.to_csv(
        "audits/grayskull_accuracy.csv",
        mode="a",
        header=not os.path.exists("audits/grayskull_accuracy.csv"),
        index=False,
    )


def main(args):
    gx = load_graph()
    ctx = MigratorSessionContext("", "", "")
    start_time = time.time()

    os.makedirs("audits", exist_ok=True)
    for k, v in AUDIT_REGISTRY.items():
        audit_dir = os.path.join("audits", k)
        version_path = os.path.join(audit_dir, "_version.json")
        audit_version = "_".join([v["version"], v["creation_version"]])
        if os.path.exists(version_path):
            version = load(open(version_path))
            # if the version of the code generating the audits is different
            # from our current audit data
            # clear out the audit data so we always use the latest version
            if version != audit_version:
                shutil.rmtree(audit_dir)
        os.makedirs(audit_dir, exist_ok=True)
        dump(audit_version, open(version_path, "w"))

    # TODO: generalize for cran skeleton
    # limit graph to things that depend on python
    python_des = nx.descendants(gx, "python")
    for node in sorted(
        python_des,
        key=lambda x: (len(nx.descendants(gx, x)), x),
        reverse=True,
    ):
        if time.time() - int(env.get("START_TIME", start_time)) > int(
            env.get("TIMEOUT", 60 * RUNTIME_MINUTES),
        ):
            break
        # depfinder only work on python at the moment so only work on things
        # with python as runtime dep
        payload = gx.nodes[node]["payload"]
        for k, v in AUDIT_REGISTRY.items():
            version = payload.get("version", None)
            ext = v["ext"]
            if (
                not payload.get("archived", False)
                and not payload.get("bad", False)
                and version
                and "python" in payload["requirements"]["run"]
                and f"{node}_{version}.{ext}" not in os.listdir(f"audits/{k}")
            ):
                fctx = FeedstockContext(
                    package_name=node,
                    feedstock_name=payload["feedstock_name"],
                    attrs=payload,
                )
                try:
                    deps = v["run"](fctx, ctx)
                except Exception as e:
                    deps = {
                        "exception": str(e),
                        "traceback": str(traceback.format_exc()).split("\n"),
                    }
                    if "dumper" in v:
                        deps = v["dumper"](deps)
                finally:
                    if deps:
                        with open(f"audits/{k}/{node}_{version}.{ext}", "w") as f:
                            v["writer"](deps, f)

    # grayskull_audit_outcome = compare_grayskull_audits(gx)
    # compute_grayskull_accuracy(grayskull_audit_outcome)
    depfinder_audit_outcome = compare_depfinder_audits(gx)
    compute_depfinder_accuracy(depfinder_audit_outcome)
