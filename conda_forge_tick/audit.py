"""Audit the dependencies of the conda-forge ecosystem"""
import os
import tempfile
import time
import traceback
from collections import defaultdict

import networkx as nx
from depfinder.main import simple_import_search
from grayskull.base.factory import GrayskullFactory
from ruamel import yaml

from conda_forge_tick.contexts import MigratorSessionContext, FeedstockContext
from conda_forge_tick.git_utils import feedstock_url
from conda_forge_tick.git_xonsh_utils import fetch_repo
from conda_forge_tick.migrators.core import _get_source_code
from conda_forge_tick.utils import load_graph, dump, load_feedstock, load
from conda_forge_tick.xonsh_utils import indir, env


def depfinder_audit_feedstock(fctx: FeedstockContext, ctx: MigratorSessionContext):
    """Uses Depfinder to audit the requirements for a python package
    """
    # get feedstock
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
        deps = simple_import_search(cb_work_dir, remap=True)
        for k in list(deps):
            deps[k] = set(deps[k])
    return deps


def grayskull_audit_feedstock(fctx: FeedstockContext, ctx: MigratorSessionContext):
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
                print(node)
                fctx = FeedstockContext(
                    package_name=node, feedstock_name=payload["name"], attrs=payload,
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

    grayskull_files = os.listdir("audits/grayskull")
    bad_inspections = {}
    if "_net_audit.json" in grayskull_files:
        grayskull_files.pop(grayskull_files.index("_net_audit.json"))
        with open("audits/grayskull/_net_audit.json", "w") as f:
            bad_inspections = load(f)
    for node, attrs in gx.nodes("payload"):
        if not attrs.get("version"):
            continue
        node_version = f"{node}_{attrs['version']}"
        if node_version in bad_inspections:
            continue
        # construct the expected filename
        expected_filename = f"{node_version}.yml"
        if expected_filename in grayskull_files:
            # load the feedstock with the grayskull meta_yaml
            try:
                with open(
                    os.path.join("audits/grayskull", expected_filename), "r",
                ) as f:
                    new_attrs = load_feedstock(node, {}, meta_yaml=f.read())
            except Exception as e:
                bad_inspections[node_version] = str(e)
                continue
            requirement_keys = [
                k
                for k in new_attrs
                if "requirements" in k
                and k not in {"requirements", "total_requirements"}
            ]
            results = defaultdict(dict)
            for k in requirement_keys:
                for kk in attrs[k]:
                    if attrs[k][kk] != new_attrs[k][kk] and (
                        kk != "test" and new_attrs[k][kk] != set("pip")
                    ):
                        results[k][kk] = {
                            "cf": attrs[k][kk],
                            "grayskull": new_attrs[k][kk],
                        }
            bad_inspections[node_version] = dict(results) or False

    with open("audits/grayskull/_net_audit.json", "w") as f:
        dump(bad_inspections, f)
