import copy
import glob
import json
import time
import traceback
import logging
import os
import typing
import networkx as nx

from urllib.error import URLError

import github3
import ruamel.yaml as yaml
from uuid import uuid4
from .xonsh_utils import indir, eval_xonsh

from conda_forge_tick.contexts import FeedstockContext
from .git_utils import (
    get_repo,
    push_repo,
    is_github_api_limit_reached,
)
from .path_lengths import cyclic_topological_sort
from .utils import (
    setup_logger,
    pluck,
    get_requirements,
    load_graph,
    dump_graph,
    LazyJson,
)
from .xonsh_utils import env
from typing import (
    List,
    Optional,
    MutableSequence,
    Sequence,
    Tuple,
    Dict,
    Set,
    MutableMapping,
)

logger = logging.getLogger("conda_forge_tick.auto_tick")

# TODO: move this back to the bot file as soon as the source issue is sorted
# https://travis-ci.org/regro/00-find-feedstocks/jobs/388387895#L1870
from .utils import frozen_to_json_friendly
from .contexts import MigratorsContext
from .migrators import (
    Migrator,
    Version,
    PipMigrator,
    LicenseMigrator,
    MigrationYaml,
    MigratorContext,
    Rebuild,
    Replacement,
    ArchRebuild,
)

from .migrators_types import *

if typing.TYPE_CHECKING:
    from .cli import CLIArgs


MIGRATORS: MutableSequence[Migrator] = [
    Version(pr_limit=30, piggy_back_migrations=[PipMigrator(), LicenseMigrator()]),
    # Noarch(pr_limit=10),
    # Pinning(pr_limit=1, removals={'perl'}),
    # Compiler(pr_limit=7),
]

BOT_RERUN_LABEL = {
    "name": "bot-rerun",
    "color": "#191970",
    "description": "Apply this label if you want the bot to retry issueing a particular pull-request",
}


def run(
    feedstock_ctx: FeedstockContext,
    migrator: Migrator,
    protocol: str = "ssh",
    pull_request: bool = True,
    rerender: bool = True,
    fork: bool = True,
    **kwargs: typing.Any,
) -> Tuple["MigrationUidTypedDict", dict]:
    """For a given feedstock and migration run the migration

    Parameters
    ----------
    feedstock_ctx: FeedstockContext
        The node attributes
    migrator: Migrator instance
        The migrator to run on the feedstock
    protocol : str, optional
        The git protocol to use, defaults to ``ssh``
    pull_request : bool, optional
        If true issue pull request, defaults to true
    rerender : bool
        Whether to rerender
    fork : bool
        If true create a fork, defaults to true
    gh : github3.GitHub instance, optional
        Object for communicating with GitHub, if None build from $USERNAME
        and $PASSWORD, defaults to None
    kwargs: dict
        The key word arguments to pass to the migrator

    Returns
    -------
    migrate_return: namedtuple
        The migration return dict used for tracking finished migrations
    pr_json: str
        The PR json object for recreating the PR as needed

    """
    # get the repo
    migrator.attrs = feedstock_ctx.attrs  # type: ignore
    feedstock_dir, repo = get_repo(
        ctx=migrator.ctx.parent,
        fctx=feedstock_ctx,
        branch=migrator.remote_branch(feedstock_ctx),
        feedstock=feedstock_ctx.feedstock_name,
        protocol=protocol,
        pull_request=pull_request,
        fork=fork,
    )

    recipe_dir = os.path.join(feedstock_dir, "recipe")
    # if postscript/activate no noarch
    script_names = ["pre-unlink", "post-link", "pre-link", "activate"]
    exts = [".bat", ".sh"]
    no_noarch_files = [
        f"{script_name}.{ext}" for script_name in script_names for ext in exts
    ]
    # TODO: Remove this
    # if isinstance(migrator, Noarch) and any(
    #     x in os.listdir(recipe_dir) for x in no_noarch_files
    # ):
    #     eval_xonsh(f"rm -rf {feedstock_dir}")
    #     return False, False
    # migrate the `meta.yaml`
    migrate_return = migrator.migrate(recipe_dir, feedstock_ctx.attrs, **kwargs)
    if not migrate_return:
        logger.critical(
            "Failed to migrate %s, %s",
            feedstock_ctx.package_name,
            feedstock_ctx.attrs.get("bad"),
        )
        eval_xonsh(f"rm -rf {feedstock_dir}")
        return False, False

    # rerender, maybe
    diffed_files: typing.List[str] = []
    with indir(feedstock_dir), env.swap(RAISE_SUBPROC_ERROR=False):
        msg = migrator.commit_message(feedstock_ctx)
        eval_xonsh("git commit -am @(msg)")
        if rerender:
            head_ref = eval_xonsh("git rev-parse HEAD")
            logger.info("Rerendering the feedstock")
            eval_xonsh("conda smithy rerender -c auto")
            # If we tried to run the MigrationYaml and rerender did nothing (we only
            # bumped the build number and dropped a yaml file in migrations) bail
            # for instance platform specific migrations
            gdiff = eval_xonsh("git diff --name-only @(head_ref)...HEAD")

            diffed_files = [
                _
                for _ in gdiff.split()
                if not (
                    _.startswith("recipe")
                    or _.startswith("migrators")
                    or _.startswith("README")
                )
            ]

    # TODO: Better annotation here
    pr_json: typing.Union[MutableMapping, None, bool]
    if isinstance(migrator, MigrationYaml) and not diffed_files:
        # spoof this so it looks like the package is done
        pr_json = {"state": "closed", "merged_at": "never issued", "id": str(uuid4())}
        ljpr = LazyJson(
            os.path.join(migrator.ctx.parent.prjson_dir, str(pr_json["id"]) + ".json"),
        )
        ljpr.update(**pr_json)
    else:
        # push up
        try:
            pr_json = push_repo(
                ctx=migrator.ctx.parent,
                fctx=feedstock_ctx,
                feedstock_dir=feedstock_dir,
                body=migrator.pr_body(feedstock_ctx),
                repo=repo,
                title=migrator.pr_title(feedstock_ctx),
                head=migrator.pr_head(feedstock_ctx),
                branch=migrator.remote_branch(feedstock_ctx),
            )

        # This shouldn't happen too often any more since we won't double PR
        except github3.GitHubError as e:
            if e.msg != "Validation Failed":
                raise
            else:
                print(f"Error during push {e}")
                # If we just push to the existing PR then do nothing to the json
                pr_json = False

    # If we've gotten this far then the node is good
    feedstock_ctx.attrs["bad"] = False
    logger.info("Removing feedstock dir")
    eval_xonsh(f"rm -rf {feedstock_dir}")
    return migrate_return, pr_json


def _requirement_names(reqlist: Optional[Sequence[Optional[str]]]) -> List[str]:
    """Parse requirement names from a list ignoring `None`
    """
    if reqlist is None:
        return []
    else:
        return [r.split()[0] for r in reqlist if r is not None]


def _host_run_test_dependencies(meta_yaml: "MetaYamlTypedDict") -> Set["PackageName"]:
    """Parse the host/run/test dependencies of a recipe

    This function parses top-level and `outputs` requirements sections.

    The complicated logic here is mainly to support not including a
    `host` section, and using `build` instead.
    """
    rq = set()
    for block in [meta_yaml] + meta_yaml.get("outputs", []) or []:
        req: "RequirementsTypedDict" = block.get("requirements", {}) or {}
        # output requirements given as list (e.g. openmotif)
        if isinstance(req, list):
            rq.update(_requirement_names(req))
            continue

        # if there is a host and it has things; use those
        if req.get("host"):
            rq.update(_requirement_names(req.get("host", [])))
        # there is no host; look at build
        elif req.get("host", "no host") not in [None, []]:
            rq.update(_requirement_names(req.get("build", []) or []))
        rq.update(_requirement_names(req.get("run", []) or []))

    # add testing dependencies
    test: "TestTypedDict" = meta_yaml.get("test", {})
    rq.update(_requirement_names(test.get("requirements")))
    rq.update(_requirement_names(test.get("requires")))

    return typing.cast("Set[PackageName]", rq)


def add_rebuild_openssl(migrators: MutableSequence[Migrator], gx: nx.DiGraph) -> None:
    """Adds rebuild openssl migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """

    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        attrs: "AttrsTypedDict" = node_attrs["payload"]
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        bh = get_requirements(meta_yaml)
        openssl_c = "openssl" in bh

        rq = _host_run_test_dependencies(meta_yaml)

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([openssl_c]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = {
        node
        for node in gx.successors("openssl")
        if (node in total_graph) and len(list(total_graph.predecessors(node))) == 0
    }
    cycles = list(nx.simple_cycles(total_graph))
    # print('cycles are here:', cycles)

    migrators.append(
        Rebuild(
            graph=total_graph,
            pr_limit=5,
            name="OpenSSL",
            top_level=top_level,
            cycles=cycles,
            obj_version=3,
        ),
    )


def add_rebuild_libprotobuf(
    migrators: MutableSequence[Migrator], gx: nx.DiGraph,
) -> None:
    """Adds rebuild libprotobuf migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """

    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        attrs: "AttrsTypedDict" = node_attrs["payload"]
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        bh = get_requirements(meta_yaml)
        protobuf_c = "libprotobuf" in bh

        rq = _host_run_test_dependencies(meta_yaml)

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([protobuf_c]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = {
        node
        for node in gx.successors("libprotobuf")
        if (node in total_graph) and len(list(total_graph.predecessors(node))) == 0
    }
    cycles = list(nx.simple_cycles(total_graph))
    # print('cycles are here:', cycles)

    migrators.append(
        Rebuild(
            graph=total_graph,
            pr_limit=5,
            name="libprotobuf-3.7",
            top_level=top_level,
            cycles=cycles,
            obj_version=3,
        ),
    )


def add_rebuild_successors(
    migrators,
    gx,
    package_name,
    pin_version,
    pr_limit=5,
    obj_version=0,
    rebuild_class=Rebuild,
):
    """Adds rebuild migrator.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.
    gx : networkx.DiGraph
        The feedstock graph
    package_name : str
        The package who's pin was moved
    pin_version : str
        The new pin value
    pr_limit : int, optional
        The number of PRs per hour, defaults to 5
    obj_version : int, optional
        The version of the migrator object (useful if there was an error)
        defaults to 0
    """

    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        attrs: "AttrsTypedDict" = node_attrs["payload"]
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        bh = get_requirements(meta_yaml)
        criteria = package_name in bh

        rq = _host_run_test_dependencies(meta_yaml)

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([criteria]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = {
        node
        for node in gx.successors(package_name)
        if (node in total_graph) and len(list(total_graph.predecessors(node))) == 0
    }
    cycles = list(nx.simple_cycles(total_graph))
    # print('cycles are here:', cycles)

    migrators.append(
        rebuild_class(
            graph=total_graph,
            pr_limit=pr_limit,
            name=f"{package_name}-{pin_version}",
            top_level=top_level,
            cycles=cycles,
            obj_version=obj_version,
        ),
    )


# def add_rebuild_blas(migrators, gx):
#     """Adds rebuild blas 2.0 migrators.
#
#     Parameters
#     ----------
#     migrators : list of Migrator
#         The list of migrators to run.
#
#     """
#     total_graph = copy.deepcopy(gx)
#
#     for node, node_attrs in gx.nodes.items():
#         attrs: "AttrsTypedDict" = node_attrs["payload"]
#         meta_yaml = attrs.get("meta_yaml", {}) or {}
#         bh = get_requirements(meta_yaml)
#         pkgs = {
#             "openblas",
#             "openblas-devel",
#             "mkl",
#             "mkl-devel",
#             "blas",
#             "lapack",
#             "clapack",
#         }
#         blas_c = len(pkgs.intersection(bh)) > 0
#
#         rq = _host_run_test_dependencies(meta_yaml)
#
#         for e in list(total_graph.in_edges(node)):
#             if e[0] not in rq:
#                 total_graph.remove_edge(*e)
#         if not any([blas_c]):
#             pluck(total_graph, node)
#
#     # post plucking we can have several strange cases, lets remove all selfloops
#     total_graph.remove_edges_from(nx.selfloop_edges(total_graph))
#
#     top_level = {
#         node for node in total_graph if not list(total_graph.predecessors(node))
#     }
#     cycles = list(nx.simple_cycles(total_graph))
#
#     migrators.append(
#         BlasRebuild(
#             graph=total_graph,
#             pr_limit=5,
#             name="blas-2.0",
#             top_level=top_level,
#             cycles=cycles,
#             obj_version=0,
#         ),
#     )


def add_replacement_migrator(
    migrators: MutableSequence[Migrator],
    gx: nx.DiGraph,
    old_pkg: "PackageName",
    new_pkg: "PackageName",
    rationale: str,
):
    """Adds a migrator to replace one package with another.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.
    gx : graph
        The conda-forge dependency graph.
    old_pkg : str
        The package to be replaced.
    new_pkg : str
        The package to replace the `old_pkg`.
    rationale : str
        The reason the for the migration. Should be a full statement.

    """
    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        attrs: "AttrsTypedDict" = node_attrs["payload"]
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        bh = get_requirements(meta_yaml)
        pkgs = {old_pkg}
        old_pkg_c = len(pkgs.intersection(bh)) > 0

        rq = _host_run_test_dependencies(meta_yaml)

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not old_pkg_c:
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = {
        node for node in total_graph if not list(total_graph.predecessors(node))
    }
    cycles = list(nx.simple_cycles(total_graph))

    migrators.append(
        Replacement(old_pkg=old_pkg, new_pkg=new_pkg, rationale=rationale, pr_limit=5),
    )


def add_arch_migrate(migrators: MutableSequence[Migrator], gx: nx.DiGraph) -> None:
    """Adds rebuild migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """
    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        attrs = node_attrs["payload"]
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        # no need to consider noarch packages for this rebuild
        noarch = meta_yaml.get("build", {}).get("noarch")
        if noarch:
            pluck(total_graph, node)
        # since we aren't building the compilers themselves, remove
        if node.endswith("_compiler_stub"):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = {
        node for node in total_graph if not set(total_graph.predecessors(node))
    }
    cycles = list(nx.simple_cycles(total_graph))
    # print('cycles are here:', cycles)

    migrators.append(
        ArchRebuild(
            graph=total_graph,
            pr_limit=5,
            name="aarch64 and ppc64le addition",
            top_level=top_level,
            cycles=cycles,
        ),
    )


def add_rebuild_migration_yaml(
    migrators: MutableSequence[Migrator],
    gx: nx.DiGraph,
    package_names: Sequence[str],
    migration_yaml: str,
    config: dict = {},
    migration_name: str = "",
    pr_limit: int = 50,
) -> None:
    """Adds rebuild migrator.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.
    gx : networkx.DiGraph
        The feedstock graph
    package_names : list of str
        The package who's pin was moved
    migration_yaml : str
        The raw yaml for the migration variant dict
    config: dict
        The __migrator contents of the migration
    migration_name: str
        Name of the migration
    pr_limit : int, optional
        The number of PRs per hour, defaults to 5
    """

    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        attrs: "AttrsTypedDict" = node_attrs["payload"]
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        # TODO: fix this, since it doesn't fully apply the strong constraints
        if "strong" in meta_yaml.get("build", {}) or any(
            [
                "strong" in output.get("build", {})
                for output in meta_yaml.get("outputs", [])
                if output.get("build")
            ],
        ):
            bh = get_requirements(meta_yaml, run=False)
        else:
            bh = get_requirements(
                meta_yaml, run=False, build=False, host=True,
            ) or get_requirements(meta_yaml, build=True, run=False, host=False)
        criteria = any(package_name in bh for package_name in package_names) and (
            "noarch" not in meta_yaml.get("build", {})
        )

        rq = _host_run_test_dependencies(meta_yaml)

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([criteria]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = {
        node
        for node in {gx.successors(package_name) for package_name in package_names}
        if (node in total_graph) and len(list(total_graph.predecessors(node))) == 0
    }
    cycles = list(nx.simple_cycles(total_graph))
    migrator = MigrationYaml(
        migration_yaml,
        graph=total_graph,
        pr_limit=pr_limit,
        name=migration_name,
        top_level=top_level,
        cycles=cycles,
        piggy_back_migrations=[PipMigrator(), LicenseMigrator()],
        **config,
    )
    print(f"bump number is {migrator.bump_number}")
    migrators.append(migrator)


def migration_factory(
    migrators: MutableSequence[Migrator], gx: nx.DiGraph, pr_limit=50,
) -> None:
    migration_yamls = []
    with indir("../conda-forge-pinning-feedstock/recipe/migrations"):
        for yaml_file in glob.glob("*.y*ml"):
            with open(yaml_file) as f:
                yaml_contents = f.read()
            migration_yamls.append((yaml_file, yaml_contents))
    for yaml_file, yaml_contents in migration_yamls:
        loaded_yaml = yaml.safe_load(yaml_contents)
        print(os.path.splitext(yaml_file)[0])

        migrator_config = loaded_yaml.get("__migrator", {})
        exclude_packages = set(migrator_config.get("exclude", []))
        package_names = (
            (set(loaded_yaml) | {l.replace("_", "-") for l in loaded_yaml})
            & set(gx.nodes)
        ) - exclude_packages

        add_rebuild_migration_yaml(
            migrators=migrators,
            gx=gx,
            package_names=list(package_names),
            migration_yaml=yaml_contents,
            migration_name=os.path.splitext(yaml_file)[0],
            config=migrator_config,
            pr_limit=pr_limit,
        )


def initialize_migrators(
    do_rebuild: bool = False,
    github_username: str = "",
    github_password: str = "",
    github_token: Optional[str] = None,
    dry_run: bool = False,
) -> Tuple[MigratorsContext, list, MutableSequence[Migrator]]:
    setup_logger(logger)
    temp = glob.glob("/tmp/*")
    gx = load_graph()
    smithy_version = eval_xonsh("conda smithy --version")
    pinning_version = json.loads(eval_xonsh("conda list conda-forge-pinning --json"))[
        0
    ]["version"]

    add_arch_migrate(MIGRATORS, gx)
    migration_factory(MIGRATORS, gx)
    for m in MIGRATORS:
        # add_replacement_migrator(
        #     $MIGRATORS, gx,
        #     'matplotlib',
        #     'matplotlib-base',
        #     ('Unless you need `pyqt`, recipes should depend only on '
        #      '`matplotlib-base`.'))
        print(f'{getattr(m, "name", m)} graph size: {len(getattr(m, "graph", []))}')

    ctx = MigratorsContext(
        circle_build_url="",
        graph=gx,
        smithy_version=smithy_version,
        pinning_version=pinning_version,
        github_username=github_username,
        github_password=github_password,
        github_token=github_token,
        dry_run=dry_run,
    )

    return ctx, temp, MIGRATORS


def migrator_status(
    migrator: Migrator, gx: nx.DiGraph,
) -> Tuple[dict, list, nx.DiGraph]:
    """Gets the migrator progress for a given migrator

    Returns
    -------
    out : dict
        Dictionary of statuses with the feedstocks in them
    order :
        Build order for this migrator
    """
    out: Dict[str, Set[str]] = {
        "done": set(),
        "in-pr": set(),
        "awaiting-pr": set(),
        "awaiting-parents": set(),
        "bot-error": set(),
    }

    gx2 = copy.deepcopy(getattr(migrator, "graph", gx))

    top_level = {node for node in gx2 if not list(gx2.predecessors(node))}
    build_sequence = list(cyclic_topological_sort(gx2, top_level))

    feedstock_metadata = dict()

    import graphviz
    from streamz.graph import _clean_text

    gv = graphviz.Digraph()
    for node, node_attrs in gx2.nodes.items():
        attrs = node_attrs["payload"]
        # remove archived from status
        if attrs.get("archived", False):
            continue
        node_metadata: Dict = {}
        feedstock_metadata[node] = node_metadata
        nuid = migrator.migrator_uid(attrs)
        for pr_json in attrs.get("PRed", []):
            if pr_json and pr_json["data"] == frozen_to_json_friendly(nuid)["data"]:
                break
        else:
            pr_json = None

        # No PR was ever issued but the migration was performed.
        # This is only the case when the migration was done manually before the bot could issue any PR.
        manually_done = pr_json is None and frozen_to_json_friendly(nuid)["data"] in (
            z["data"] for z in attrs.get("PRed", [])
        )

        buildable = not migrator.filter(attrs)
        fntc = "black"
        if manually_done:
            out["done"].add(node)
            fc = "#440154"
            fntc = "white"
        elif pr_json is None:
            if buildable:
                out["awaiting-pr"].add(node)
                fc = "#35b779"
            else:
                out["awaiting-parents"].add(node)
                fc = "#fde725"
        elif "PR" not in pr_json:
            out["bot-error"].add(node)
            fc = "#000000"
            fntc = "white"
        elif pr_json["PR"]["state"] == "closed":
            out["done"].add(node)
            fc = "#440154"
            fntc = "white"
        else:
            out["in-pr"].add(node)
            fc = "#31688e"
            fntc = "white"
        if node not in out["done"]:
            gv.node(
                node,
                label=_clean_text(node),
                fillcolor=fc,
                style="filled",
                fontcolor=fntc,
            )

        # additional metadata for reporting
        node_metadata["num_descendants"] = len(nx.descendants(gx2, node))
        node_metadata["immediate_children"] = [
            k
            for k in sorted(gx2.successors(node))
            if not gx2[k].get("payload", {}).get("archived", False)
        ]
        if pr_json and "PR" in pr_json:
            # I needed to fake some PRs they don't have html_urls though
            node_metadata["pr_url"] = pr_json["PR"].get("html_url", "")

    out2: Dict = {}
    for k in out.keys():
        out2[k] = list(
            sorted(
                out[k],
                key=lambda x: build_sequence.index(x) if x in build_sequence else -1,
            ),
        )

    out2["_feedstock_status"] = feedstock_metadata
    for (e0, e1), edge_attrs in gx2.edges.items():
        if (
            e0 not in out["done"]
            and e1 not in out["done"]
            and not gx2.nodes[e0]["payload"].get("archived", False)
            and not gx2.nodes[e1]["payload"].get("archived", False)
        ):
            gv.edge(e0, e1)

    return out2, build_sequence, gv


def main(args: "CLIArgs") -> None:
    github_username = env.get("USERNAME", "")
    github_password = env.get("PASSWORD", "")
    github_token = env.get("GITHUB_TOKEN")
    global MIGRATORS
    mctx, temp, MIGRATORS = initialize_migrators(
        do_rebuild=False,
        github_username=github_username,
        github_password=github_password,
        dry_run=args.dry_run,
        github_token=github_token,
    )

    for migrator in MIGRATORS:

        mmctx = MigratorContext(parent=mctx, migrator=migrator)
        migrator.bind_to_ctx(mmctx)

        good_prs = 0
        effective_graph = mmctx.effective_graph

        logger.info(
            "Total migrations for %s: %d",
            migrator.__class__.__name__,
            len(effective_graph.nodes),
        )

        top_level = {
            node
            for node in effective_graph
            if not list(effective_graph.predecessors(node))
        }
        # print(list(migrator.order(effective_graph, gx)))
        for node_name in migrator.order(effective_graph, mctx.graph):
            with mctx.graph.nodes[node_name]["payload"] as attrs:
                # Don't let CI timeout, break ahead of the timeout so we make certain
                # to write to the repo
                # TODO: convert these env vars
                if (
                    time.time() - int(env["START_TIME"]) > int(env["TIMEOUT"])
                    or good_prs >= migrator.pr_limit
                ):
                    break

                fctx = FeedstockContext(
                    package_name=node_name,
                    feedstock_name=attrs["feedstock_name"],
                    attrs=attrs,
                )

                logger.info(
                    "%s IS MIGRATING %s",
                    migrator.__class__.__name__.upper(),
                    fctx.package_name,
                )
                try:
                    # Don't bother running if we are at zero
                    if (
                        not args.dry_run
                        and mctx.gh.rate_limit()["resources"]["core"]["remaining"] == 0
                    ):
                        break
                    rerender = (
                        attrs.get("smithy_version") != mctx.smithy_version
                        or attrs.get("pinning_version") != mctx.pinning_version
                        or migrator.rerender
                    )
                    migrator_uid, pr_json = run(
                        feedstock_ctx=fctx,
                        migrator=migrator,
                        rerender=rerender,
                        protocol="https",
                        hash_type=attrs.get("hash_type", "sha256"),
                    )
                    # if migration successful
                    if migrator_uid:
                        d = frozen_to_json_friendly(migrator_uid)
                        # if we have the PR already do nothing
                        if d["data"] in [
                            existing_pr["data"] for existing_pr in attrs.get("PRed", [])
                        ]:
                            pass
                        else:
                            if not pr_json:
                                pr_json = {
                                    "state": "closed",
                                    "head": {"ref": "<this_is_not_a_branch>"},
                                }
                            d.update(PR=pr_json)
                            attrs.setdefault("PRed", []).append(d)
                        attrs.update(
                            {
                                "smithy_version": mctx.smithy_version,
                                "pinning_version": mctx.pinning_version,
                            },
                        )

                except github3.GitHubError as e:
                    if e.msg == "Repository was archived so is read-only.":
                        attrs["archived"] = True
                    else:
                        logger.critical(
                            "GITHUB ERROR ON FEEDSTOCK: %s", fctx.feedstock_name,
                        )
                        if is_github_api_limit_reached(e, mctx.gh):
                            break
                except URLError as e:
                    logger.exception("URLError ERROR")
                    attrs["bad"] = {
                        "exception": str(e),
                        "traceback": str(traceback.format_exc()).split("\n"),
                        "code": getattr(e, "code"),
                        "url": getattr(e, "url"),
                    }
                except Exception as e:
                    logger.exception("NON GITHUB ERROR")
                    attrs["bad"] = {
                        "exception": str(e),
                        "traceback": str(traceback.format_exc()).split("\n"),
                    }
                else:
                    if migrator_uid:
                        # On successful PR add to our counter
                        good_prs += 1
                finally:
                    # Write graph partially through
                    dump_graph(mctx.graph)

                    eval_xonsh(f"rm -rf {mctx.rever_dir}/*")
                    logger.info(eval_xonsh("![pwd]"))
                    for f in glob.glob("/tmp/*"):
                        if f not in temp:
                            eval_xonsh(f"rm -rf {f}")

    logger.info(
        "API Calls Remaining: %d",
        mctx.gh.rate_limit()["resources"]["core"]["remaining"],
    )
    logger.info("Done")


if __name__ == "__main__":

    pass  #  main()
