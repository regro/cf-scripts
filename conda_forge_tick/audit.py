"""Audit the dependencies of the conda-forge ecosystem"""
import os
import traceback
import tempfile

import networkx as nx
import time
from depfinder.main import simple_import_search
from grayskull.base.factory import GrayskullFactory

from conda_forge_tick.contexts import MigratorSessionContext, FeedstockContext
from conda_forge_tick.git_utils import feedstock_url
from conda_forge_tick.git_xonsh_utils import fetch_repo
from conda_forge_tick.migrators.core import _get_source_code
from conda_forge_tick.utils import load_graph, dump
from conda_forge_tick.xonsh_utils import indir, env


def depfinder_audit_feedstock(fctx: FeedstockContext, ctx: MigratorSessionContext):
    """Uses Depfinder to audit the requirements for a python package
    """
    # get feedstock
    feedstock_dir = os.path.join(ctx.rever_dir, fctx.package_name + "-feedstock")
    origin = feedstock_url(fctx=fctx, protocol="https")
    fetch_repo(
        feedstock_dir=feedstock_dir, origin=origin, upstream=origin, branch="master"
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
    pkg_name = fctx.attrs['name']
    pkg_version = fctx.attrs['version']
    recipe = GrayskullFactory.create_recipe("pypi", pkg_name, pkg_version, download=False)

    with tempfile.TemporaryDirectory() as td:
        recipe.generate_recipe(td, mantainers=list({m: None for m in fctx.attrs['meta_yaml']['extra']['recipe-maintainers']}))
        with open(os.path.join(td, pkg_name, 'meta.yaml'), 'r') as f:
            out = f.read()
    return out


AUDIT_REGISTRY = {
    'depfinder': depfinder_audit_feedstock,
    'grayskull': grayskull_audit_feedstock
}


def main(args):
    gx = load_graph()
    ctx = MigratorSessionContext("", "", "")
    start_time = time.time()
    # limit graph to things that depend on python
    python_des = nx.descendants(gx, "pypy-meta")
    os.makedirs("audits", exist_ok=True)
    for node in sorted(
        python_des, key=lambda x: (len(nx.descendants(gx, x)), x), reverse=True,
    ):
        if time.time() - int(env.get("START_TIME", start_time)) > int(
            env.get("TIMEOUT", 60*30)
        ):
            break
        # depfinder only work on python at the moment so only work on things
        # with python as runtime dep
        with gx.nodes[node]["payload"] as payload:
            version = payload.get('version', None)
            if (
                not payload.get("archived", False)
                and version
                and "python" in payload["requirements"]["run"]
                and f'{node}_{version}.json' not in os.listdir("audits")
            ):
                print(node)
                fctx = FeedstockContext(
                    package_name=node, feedstock_name=payload["name"], attrs=payload
                )
                try:
                    deps = depfinder_audit_feedstock(fctx, ctx)
                except Exception as e:
                    deps = {
                        "exception": str(e),
                        "traceback": str(traceback.format_exc()).split("\n"),
                    }
                finally:
                    with open(f"audits/{node}_{version}.json", "w") as f:
                        dump(deps, f)
