"""Audit the dependencies of the conda-forge ecosystem"""
import os
import tempfile
import time
import traceback
from collections import defaultdict
from concurrent.futures._base import as_completed

import networkx as nx
from depfinder.main import simple_import_search
from grayskull.base.factory import GrayskullFactory
from ruamel import yaml

from conda_forge_tick.contexts import MigratorSessionContext, FeedstockContext
from conda_forge_tick.git_utils import feedstock_url
from conda_forge_tick.git_xonsh_utils import fetch_repo
from conda_forge_tick.migrators.core import _get_source_code
from conda_forge_tick.utils import load_graph, dump, load_feedstock, load, executor
from conda_forge_tick.xonsh_utils import indir, env

DEPFINDER_IGNORE = ["*/docs/*", "*/tests/*", "*/test/*", "*/doc/*", "*/testdir/*"]


def depfinder_audit_feedstock(
    fctx: FeedstockContext, ctx: MigratorSessionContext, import_cf_map=None,
):
    """Uses Depfinder to audit the requirements for a python package
    """
    # get feedstock
    if import_cf_map is None:
        import_cf_map = {}
    feedstock_dir = os.path.join(ctx.rever_dir, fctx.package_name + "-feedstock")
    origin = feedstock_url(fctx=fctx, protocol="https")
    fetch_repo(
        feedstock_dir=feedstock_dir, origin=origin, upstream=origin, branch="master",
    )
    recipe_dir = os.path.join(feedstock_dir, "recipe")

    # get source code
    cb_work_dir = _get_source_code(recipe_dir)
    with indir(cb_work_dir):
        # run depfinder on source code
        deps = simple_import_search(
            cb_work_dir,
            # remap=True,
            ignore=DEPFINDER_IGNORE,
        )
        for k in list(deps):
            deps[k] = {import_cf_map.get(v, v) for v in deps[k]}
    return deps


def grayskull_audit_feedstock(
    fctx: FeedstockContext, ctx: MigratorSessionContext, import_cf_map=None,
):
    """Uses grayskull to audit the requirements for a python package
    """
    # TODO: come back to this, since CF <-> PyPI is not one-to-one and onto
    pkg_name = fctx.package_name
    pkg_version = fctx.attrs["version"]
    recipe = GrayskullFactory.create_recipe(
        "pypi", pkg_name, pkg_version, download=False,
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
        with open(os.path.join(td, pkg_name, "meta.yaml"), "r") as f:
            out = f.read()
    return out


AUDIT_REGISTRY = {
    "depfinder": {"run": depfinder_audit_feedstock, "writer": dump, "ext": "json"},
    # Grayskull produces a valid meta.yaml, there is no in memory representation for that so we just write out the
    # string
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
        with open("audits/grayskull/_net_audit.json", "r") as f:
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
                    os.path.join("audits/grayskull", expected_filename), "r",
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


def compare_depfinder_audits(gx):
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
            with open(os.path.join("audits/depfinder", expected_filename), "r") as f:
                output = load(f)
            if isinstance(output, str):
                bad_inspection[node_version] = output
                continue
            quest = output.get("questionable", set())
            required_pkgs = output.get("required", set())
            d = {}
            run_req = attrs["requirements"]["run"]
            excludes = {
                node,
                node.replace("-", "_"),
                node.replace("_", "-"),
                "python",
                "setuptools",
            }
            cf_minus_df = run_req - required_pkgs - excludes - quest
            if cf_minus_df:
                d.update(cf_minus_df=cf_minus_df)
            df_minus_cf = required_pkgs - run_req - excludes
            if df_minus_cf:
                d.update(df_minus_cf=df_minus_cf)
            bad_inspection[node_version] = d or False
    with open("audits/depfinder/_net_audit.json", "w") as f:
        dump(bad_inspection, f)
    return bad_inspection


def main(args):
    gx = load_graph()
    ctx = MigratorSessionContext("", "", "")
    start_time = time.time()

    os.makedirs("audits", exist_ok=True)
    for k in AUDIT_REGISTRY:
        os.makedirs(os.path.join("audits", k), exist_ok=True)

    raw_import_map = yaml.load(open("mappings/pypi/name_mapping.yaml"))
    import_map = {
        item["import_name"]: item.get("conda_name", item.get("conda_forge"))
        for item in raw_import_map
    }

    # TODO: generalize for cran skeleton
    # limit graph to things that depend on python
    python_des = nx.descendants(gx, "pypy-meta")
    for node in sorted(
        python_des, key=lambda x: (len(nx.descendants(gx, x)), x), reverse=True,
    ):
        if time.time() - int(env.get("START_TIME", start_time)) > int(
            env.get("TIMEOUT", 60 * 30),
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
                    package_name=node, feedstock_name=payload["name"], attrs=payload,
                )
                try:
                    deps = v["run"](fctx, ctx, import_map)
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
    compare_depfinder_audits(gx)
