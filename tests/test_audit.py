import os

from conda_forge_tick.audit import audit_feedstock
from conda_forge_tick.contexts import FeedstockContext, MigratorSessionContext
import networkx as nx

from conda_forge_tick.utils import load

G = nx.DiGraph()
G.add_node("conda", reqs=["python"])


def test_audit_feedstock():
    mm_ctx = MigratorSessionContext(
        graph=G,
        smithy_version="",
        pinning_version="",
        github_username="",
        github_password="",
        circle_build_url="",
    )
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"), "r"
    ) as f:
        attrs = load(f)
    fctx = FeedstockContext("depfinder", "depfinder", attrs)

    deps = audit_feedstock(fctx, mm_ctx)
    assert deps == {
        "required": {"setuptools", "versioneer", "stdlib-list", "pyyaml"},
        "questionable": {"setuptools", "ipython", "ConfigParser", "cx_Freeze"},
        "builtin": {
            "errno",
            "__future__",
            "collections",
            "logging",
            "pprint",
            "pkgutil",
            "configparser",
            "os",
            "argparse",
            "subprocess",
            "pdb",
            "json",
            "io",
            "copy",
            "fnmatch",
            "ast",
            "distutils",
            "itertools",
            "re",
            "sys",
        },
        "relative": {"main", "_version"},
    }
