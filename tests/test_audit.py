import os

from conda_forge_tick.contexts import FeedstockContext, MigratorSessionContext
import networkx as nx

from conda_forge_tick.utils import load
import pytest


G = nx.DiGraph()
G.add_node("conda", reqs=["python"])


@pytest.mark.skip(reason="fails on linux but not locally on osx")
def test_depfinder_audit_feedstock():
    from conda_forge_tick.audit import depfinder_audit_feedstock

    mm_ctx = MigratorSessionContext(
        graph=G,
        smithy_version="",
        pinning_version="",
        github_username="",
        github_password="",
        circle_build_url="",
    )
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    fctx = FeedstockContext("depfinder", "depfinder", attrs)

    deps = depfinder_audit_feedstock(fctx, mm_ctx)
    assert deps == {
        "builtin": {
            "ConfigParser",
            "__future__",
            "argparse",
            "ast",
            "collections",
            "configparser",
            "copy",
            "distutils.command.build_py",
            "distutils.command.sdist",
            "distutils.core",
            "errno",
            "fnmatch",
            "io",
            "itertools",
            "json",
            "logging",
            "os",
            "pdb",
            "pkgutil",
            "pprint",
            "re",
            "subprocess",
            "sys",
        },
        "questionable": {"setuptools", "ipython", "cx_freeze"},
        "required": {"pyyaml", "stdlib-list", "setuptools", "versioneer"},
    }


def test_grayskull_audit_feedstock():
    from conda_forge_tick.audit import grayskull_audit_feedstock

    mm_ctx = MigratorSessionContext(
        graph=G,
        smithy_version="",
        pinning_version="",
        github_username="",
        github_password="",
        circle_build_url="",
    )
    with open(
        os.path.join(os.path.dirname(__file__), "test_yaml", "depfinder.json"),
    ) as f:
        attrs = load(f)
    fctx = FeedstockContext("depfinder", "depfinder", attrs)

    recipe = grayskull_audit_feedstock(fctx, mm_ctx)
    assert recipe != ""
