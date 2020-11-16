"""Audit the dependencies of the conda-forge ecosystem"""
import os
import tempfile
import time
import traceback
from collections import defaultdict
from concurrent.futures._base import as_completed
from typing import Dict

import networkx as nx
from stdlib_list import stdlib_list

from depfinder.main import simple_import_search
from grayskull.base.factory import GrayskullFactory
from ruamel import yaml
import pandas as pd

from conda_forge_tick.contexts import MigratorSessionContext, FeedstockContext
from conda_forge_tick.git_utils import feedstock_url, fetch_repo
from conda_forge_tick.utils import (
    load_graph,
    dump,
    load_feedstock,
    load,
    executor,
    as_iterable,
    _get_source_code,
)
from conda_forge_tick.xonsh_utils import indir, env

IGNORE_STUBS = ["doc", "example", "demo", "test"]
IGNORE_TEMPLATES = ["*/{z}/*", "*/{z}s/*"]
DEPFINDER_IGNORE = []
for k in IGNORE_STUBS:
    for tmpl in IGNORE_TEMPLATES:
        DEPFINDER_IGNORE.append(tmpl.format(z=k))
DEPFINDER_IGNORE += [
    "*testdir/*",
    "*conftest*",
]

STATIC_EXCLUDES = {
    "python",
    "setuptools",
    "pip",
    "versioneer",
    # bad pypi mapping
    "futures",
}.union(
    # Some libs support older python versions, we don't want their std lib
    # entries in our diff though
    *[set(stdlib_list(k)) for k in ["2.7", "3.5", "3.6", "3.7"]]
)


def extract_deps_from_source(recipe_dir):
    cb_work_dir = _get_source_code(recipe_dir)
    with indir(cb_work_dir):
        # run depfinder on source code
        imports = simple_import_search(cb_work_dir, ignore=DEPFINDER_IGNORE)
    return {k: set(v) for k, v in imports.items()}


def depfinder_audit_feedstock(fctx: FeedstockContext, ctx: MigratorSessionContext):
    """Uses Depfinder to audit the imports for a python package"""
    # get feedstock
    feedstock_dir = os.path.join(ctx.rever_dir, fctx.package_name + "-feedstock")
    origin = feedstock_url(fctx=fctx, protocol="https")
    fetch_repo(
        feedstock_dir=feedstock_dir,
        origin=origin,
        upstream=origin,
        branch="master",
    )
    recipe_dir = os.path.join(feedstock_dir, "recipe")

    return extract_deps_from_source(recipe_dir)


def grayskull_audit_feedstock(fctx: FeedstockContext, ctx: MigratorSessionContext):
    """Uses grayskull to audit the requirements for a python package"""
    # TODO: come back to this, since CF <-> PyPI is not one-to-one and onto
    pkg_name = fctx.package_name
    pkg_version = fctx.attrs["version"]
    recipe = GrayskullFactory.create_recipe(
        "pypi",
        pkg_name,
        pkg_version,
        download=False,
    )

    with tempfile.TemporaryDirectory() as td:
        recipe.generate_recipe(
            td,
            mantainers=list(
                {
                    m: None
                    for m in fctx.attrs["meta_yaml"]["extra"]["recipe-maintainers"]
                },
            ),
        )
        with open(os.path.join(td, pkg_name, "meta.yaml")) as f:
            out = f.read()
    return out


AUDIT_REGISTRY = {
    "depfinder": {"run": depfinder_audit_feedstock, "writer": dump, "ext": "json"},
    # Grayskull produces a valid meta.yaml, there is no in memory representation
    # for that so we just write out the string
    "grayskull": {
        "run": grayskull_audit_feedstock,
        "writer": lambda x, f: f.write(x),
        "dumper": yaml.dump,
        "ext": "yml",
    },
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


def extract_missing_packages(
    required_imports,
    questionable_imports,
    run_packages,
    package_by_import,
    import_by_package,
    node,
    nodes,
):
    exclude_packages = STATIC_EXCLUDES.union(
        {node, node.replace("-", "_"), node.replace("_", "-")},
    )

    questionable_packages = set().union(
        *list(as_iterable(package_by_import.get(k, k)) for k in questionable_imports)
    )
    required_packages = set().union(
        *list(as_iterable(package_by_import.get(k, k)) for k in required_imports)
    )

    run_imports = set().union(
        *list(as_iterable(import_by_package.get(k, k)) for k in run_packages)
    )
    exclude_imports = set().union(
        *list(as_iterable(import_by_package.get(k, k)) for k in exclude_packages)
    )

    d = {}
    # These are all normalized to packages
    # packages who's libraries are not imported
    cf_minus_df = (
        run_packages - required_packages - exclude_packages - questionable_packages
    ) & nodes
    if cf_minus_df:
        d.update(cf_minus_df=cf_minus_df)

    # These are all normalized to imports
    # imports which have no associated package in the meta.yaml
    df_minus_cf_imports = required_imports - run_imports - exclude_imports
    # Normalize to packages, the native interface for conda-forge
    # Note that the set overlap is a bit of a hack, sources could have imports we
    # don't ship at all
    df_minus_cf = (
        set().union(
            *list(as_iterable(package_by_import.get(k, k)) for k in df_minus_cf_imports)
        )
        & nodes
    )
    if df_minus_cf:
        d.update(df_minus_cf=df_minus_cf)
    return d


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


def create_package_import_maps(nodes, mapping_yaml="mappings/pypi/name_mapping.yaml"):
    raw_import_map = yaml.safe_load(open(mapping_yaml))
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
    python_nodes: set,
    imports_by_package,
    packages_by_import,
) -> Dict[str, set]:
    d = extract_missing_packages(
        required_imports=deps.get("required", set()),
        questionable_imports=deps.get("questionable", set()),
        run_packages=attrs["requirements"]["run"],
        package_by_import=packages_by_import,
        import_by_package=imports_by_package,
        node=node,
        nodes=python_nodes,
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
    imports_by_package, packages_by_import = create_package_import_maps(
        python_nodes,
        # set(gx.nodes)
    )

    bad_inspection = {}
    files = os.listdir("audits/depfinder")

    if "_net_audit.json" in files:
        files.pop(files.index("_net_audit.json"))

    for node, attrs in gx.nodes("payload"):
        if not attrs.get("version"):
            continue
        node_version = f"{node}_{attrs['version']}"
        # construct the expected filename
        expected_filename = f"{node_version}.json"
        if expected_filename in files:
            with open(os.path.join("audits/depfinder", expected_filename)) as f:
                output = load(f)
            if isinstance(output, str):
                bad_inspection[node_version] = output
                continue
            d = extract_missing_packages(
                required_imports=output.get("required", set()),
                questionable_imports=output.get("questionable", set()),
                run_packages=attrs["requirements"]["run"],
                package_by_import=packages_by_import,
                import_by_package=imports_by_package,
                node=node,
                nodes=python_nodes,
                # set(gx.nodes)
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
    }
    for k, v in bad_inspection.items():
        if not v:
            count["accurate"] += 1
        elif "cf_minus_df" in v and "df_minus_cf" in v:
            count["cf_over_and_under_specified"] += 1
        elif "cf_minus_df" in v:
            count["cf_under_specified"] += 1
        else:
            count["cf_over_specified"] += 1
    df = pd.DataFrame.from_dict(count, orient='index').T
    df.to_csv(
        "audits/depfinder_accuracy.csv",
        mode="a",
        header=not os.path.exists("audits/depfinder_accuracy.csv"),
        index=False
    )


def main(args):
    gx = load_graph()
    ctx = MigratorSessionContext("", "", "")
    start_time = time.time()

    os.makedirs("audits", exist_ok=True)
    for k in AUDIT_REGISTRY:
        os.makedirs(os.path.join("audits", k), exist_ok=True)

    # TODO: generalize for cran skeleton
    # limit graph to things that depend on python
    python_des = nx.descendants(gx, "pypy-meta")
    for node in sorted(
        python_des,
        key=lambda x: (len(nx.descendants(gx, x)), x),
        reverse=True,
    ):
        if time.time() - int(env.get("START_TIME", start_time)) > int(
            env.get("TIMEOUT", 60 * 45),
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
                and version
                and "python" in payload["requirements"]["run"]
                and f"{node}_{version}.{ext}" not in os.listdir(f"audits/{k}")
            ):
                fctx = FeedstockContext(
                    package_name=node,
                    feedstock_name=payload["name"],
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
                    with open(f"audits/{k}/{node}_{version}.{ext}", "w") as f:
                        v["writer"](deps, f)

    compare_grayskull_audits(gx)
    depfinder_audit_outcome = compare_depfinder_audits(gx)
    compute_depfinder_accuracy(depfinder_audit_outcome)
