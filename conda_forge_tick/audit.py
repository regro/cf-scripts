import os
import traceback

import networkx as nx
import time
from depfinder.main import simple_import_search

from conda_forge_tick.contexts import MigratorSessionContext, FeedstockContext
from conda_forge_tick.git_utils import feedstock_url
from conda_forge_tick.git_xonsh_utils import fetch_repo
from conda_forge_tick.migrators.core import _get_source_code
from conda_forge_tick.utils import load_graph
from conda_forge_tick.xonsh_utils import indir, env


def audit_feedstock(fctx: FeedstockContext, ctx: MigratorSessionContext):
    """Uses Depfinder to audit the requirements for a python package

    Parameters
    ----------
    feedstock_attrs

    Returns
    -------

    """
    # get feedstock
    feedstock_dir = os.path.join(ctx.rever_dir,
                                 fctx.package_name + "-feedstock")
    origin = feedstock_url(fctx=fctx)
    fetch_repo(feedstock_dir=feedstock_dir, origin=origin, upstream=origin,
               branch='master')
    recipe_dir = os.path.join(feedstock_dir, "recipe")

    # get source code
    cb_work_dir = _get_source_code(recipe_dir)
    with indir(cb_work_dir):
        # run depfinder on source code
        deps = simple_import_search(cb_work_dir, remap=True)
        for k in list(deps):
            deps[k] = set(deps[k])
    return deps


def main(args):
    gx = load_graph()
    ctx = MigratorSessionContext('', '', '')
    start_time = time.time()
    # limit graph to things that depend on python
    python_des = nx.descendants(gx, 'python')
    for node in sorted(
            python_des, key=lambda x: (len(nx.descendants(gx, x)), x), reverse=True,
    ):
        if (
                time.time() - int(
            env.get("START_TIME", start_time))
                > int(env.get("TIMEOUT", 60))
        ):
            break
        # depfinder only work on python at the moment so only work on things
        # with python as runtime dep
        with gx.nodes[node]['payload'] as payload:
            if not payload.get('archived', False) and 'python' in payload['requirements']['run'] and 'depfinder_audit' not in payload:
                print(node)
                fctx = FeedstockContext(package_name=node,
                                        feedstock_name=payload['name'],
                                        attrs=payload)
                try:
                    deps = audit_feedstock(fctx, ctx)
                except Exception as e:
                    deps = {"exception": str(e),
                            "traceback": str(traceback.format_exc()).split("\n"),}
                finally:
                    payload['depfinder_audit'] = deps

