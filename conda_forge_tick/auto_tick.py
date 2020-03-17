import copy
import glob
import json
import re

import time
import traceback
import logging
import os
import typing
import networkx as nx
from conda.models.version import VersionOrder
from conda_build.config import Config
from conda_build.variants import parse_config_file

from urllib.error import URLError

import github3
import ruamel.yaml as yaml
from uuid import uuid4

from conda_forge_tick.migrators.migration_yaml import MigrationYamlCreator
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
    load_graph,
    dump_graph,
    LazyJson,
    CB_CONFIG,
    parse_meta_yaml,
)
from .xonsh_utils import env
from typing import (
    Optional,
    MutableSequence,
    MutableSet,
    Sequence,
    Tuple,
    Dict,
    Set,
    Mapping,
    MutableMapping,
    Union,
)

from conda_forge_tick.utils import frozen_to_json_friendly
from conda_forge_tick.contexts import MigratorSessionContext, MigratorContext
from conda_forge_tick.migrators import (
    Migrator,
    Version,
    PipMigrator,
    LicenseMigrator,
    MigrationYaml,
    Replacement,
    ArchRebuild,
    MatplotlibBase,
    CondaForgeYAMLCleanup,
    ExtraJinja2KeysCleanup,
)

if typing.TYPE_CHECKING:
    from .cli import CLIArgs
    from .migrators_types import (
        MetaYamlTypedDict,
        PackageName,
        AttrsTypedDict,
    )

logger = logging.getLogger("conda_forge_tick.auto_tick")


PR_LIMIT = 5

MIGRATORS: MutableSequence[Migrator] = [
    Version(
        pr_limit=PR_LIMIT * 2,
        piggy_back_migrations=[
            PipMigrator(),
            LicenseMigrator(),
            CondaForgeYAMLCleanup(),
            ExtraJinja2KeysCleanup(),
        ],
    ),
]

BOT_RERUN_LABEL = {
    "name": "bot-rerun",
    "color": "#191970",
    "description": (
        "Apply this label if you want the bot to retry "
        "issueing a particular pull-request"
    ),
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
    migrate_return: MigrationUidTypedDict
        The migration return dict used for tracking finished migrations
    pr_json: dict
        The PR json object for recreating the PR as needed

    """
    # get the repo
    # TODO: stop doing this.
    migrator.attrs = feedstock_ctx.attrs  # type: ignore

    # TODO: run this in parallel
    feedstock_dir, repo = get_repo(
        ctx=migrator.ctx.session,
        fctx=feedstock_ctx,
        branch=migrator.remote_branch(feedstock_ctx),
        feedstock=feedstock_ctx.feedstock_name,
        protocol=protocol,
        pull_request=pull_request,
        fork=fork,
    )

    recipe_dir = os.path.join(feedstock_dir, "recipe")

    # migrate the feedstock
    migrator.run_pre_piggyback_migrations(recipe_dir, feedstock_ctx.attrs, **kwargs)

    # TODO - make a commit here if the repo changed

    migrate_return = migrator.migrate(recipe_dir, feedstock_ctx.attrs, **kwargs)

    if not migrate_return:
        logger.critical(
            "Failed to migrate %s, %s",
            feedstock_ctx.package_name,
            feedstock_ctx.attrs.get("bad"),
        )
        eval_xonsh(f"rm -rf {feedstock_dir}")
        return False, False

    # TODO - commit main migration here

    migrator.run_post_piggyback_migrations(recipe_dir, feedstock_ctx.attrs, **kwargs)

    # TODO commit post migration here

    # rerender, maybe
    diffed_files: typing.List[str] = []
    with indir(feedstock_dir), env.swap(RAISE_SUBPROC_ERROR=False):
        msg = migrator.commit_message(feedstock_ctx)  # noqa
        eval_xonsh("git add --all .")
        eval_xonsh("git commit -am @(msg)")
        if rerender:
            head_ref = eval_xonsh("git rev-parse HEAD")  # noqa
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
        pr_json = {
            "state": "closed",
            "merged_at": "never issued",
            "id": str(uuid4()),
        }
    else:
        # push up
        try:
            pr_json = push_repo(
                session_ctx=migrator.ctx.session,
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
                ljpr = False
    if pr_json:
        ljpr = LazyJson(
            os.path.join(migrator.ctx.session.prjson_dir, str(pr_json["id"]) + ".json"),
        )
        ljpr.update(**pr_json)

        from .dynamo_models import PRJson

        PRJson.dump(pr_json)
    # If we've gotten this far then the node is good
    feedstock_ctx.attrs["bad"] = False
    logger.info("Removing feedstock dir")
    eval_xonsh(f"rm -rf {feedstock_dir}")
    return migrate_return, ljpr


def _host_run_test_dependencies(meta_yaml: "MetaYamlTypedDict",) -> Set["PackageName"]:
    """Parse the host/run/test dependencies of a recipe

    This function parses top-level and `outputs` requirements sections.

    The complicated logic here is mainly to support not including a
    `host` section, and using `build` instead.
    """
    _ = meta_yaml["requirements"]
    rq = (_["host"] or _["build"]) | _["run"] | _["test"]
    return typing.cast("Set[PackageName]", rq)


def add_replacement_migrator(
    migrators: MutableSequence[Migrator],
    gx: nx.DiGraph,
    old_pkg: "PackageName",
    new_pkg: "PackageName",
    rationale: str,
    alt_migrator: Union[Migrator, None] = None,
) -> None:
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
    alt_migrator : Replacement migrator or a sublcass thereof
        An alternate Replacement migrator to use for special tasks.

    """
    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        requirements = node_attrs["payload"].get("requirements", {})
        rq = (
            requirements.get("build", set())
            | requirements.get("host", set())
            | requirements.get("run", set())
            | requirements.get("test", set())
        )
        pkgs = {old_pkg}
        old_pkg_c = pkgs.intersection(rq)

        if not old_pkg_c:
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    if alt_migrator is not None:
        migrators.append(
            alt_migrator(
                old_pkg=old_pkg,
                new_pkg=new_pkg,
                rationale=rationale,
                pr_limit=PR_LIMIT,
                graph=total_graph,
            ),
        )
    else:
        migrators.append(
            Replacement(
                old_pkg=old_pkg,
                new_pkg=new_pkg,
                rationale=rationale,
                pr_limit=PR_LIMIT,
                graph=total_graph,
            ),
        )


def add_arch_migrate(migrators: MutableSequence[Migrator], gx: nx.DiGraph) -> None:
    """Adds rebuild migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """
    total_graph = copy.deepcopy(gx)

    migrators.append(
        ArchRebuild(
            graph=total_graph, pr_limit=PR_LIMIT, name="aarch64 and ppc64le addition",
        ),
    )


def add_rebuild_migration_yaml(
    migrators: MutableSequence[Migrator],
    gx: nx.DiGraph,
    package_names: Sequence[str],
    output_to_feedstock: Mapping[str, str],
    excluded_feedstocks: MutableSet[str],
    migration_yaml: str,
    config: dict = {},
    migration_name: str = "",
    pr_limit: int = PR_LIMIT,
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
    output_to_feedstock : dict of str
        Mapping of output name to feedstock name
    excluded_feedstocks : set of str
        Feedstock names which should never be included in the migration
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
        requirements = attrs.get("requirements", {})
        host = requirements.get("host", set())
        build = requirements.get("build", set())
        bh = host or build
        criteria = bh & set(package_names) and (
            "noarch" not in attrs.get("meta_yaml", {}).get("build", {})
        )
        # get host/build, run and test and launder them through outputs
        # this should fix outputs related issues (eg gdal)
        rq = set(
            map(
                lambda x: gx.graph["outputs_lut"].get(x, x),
                (host or build)
                | requirements.get("run", set())
                | requirements.get("test", set()),
            )
        )

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([criteria]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    package_names = {
        p if p in gx.nodes else output_to_feedstock[p] for p in package_names
    } - excluded_feedstocks

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
        piggy_back_migrations=[
            PipMigrator(),
            LicenseMigrator(),
            CondaForgeYAMLCleanup(),
            ExtraJinja2KeysCleanup(),
        ],
        **config,
    )
    print(f"bump number is {migrator.bump_number}")
    migrators.append(migrator)


def migration_factory(
    migrators: MutableSequence[Migrator], gx: nx.DiGraph, pr_limit: int = PR_LIMIT,
) -> None:
    migration_yamls = []
    migrations_loc = os.path.join(
        os.environ["CONDA_PREFIX"],
        "share",
        "conda-forge",
        "migrations",
    )
    with indir(migrations_loc):
        for yaml_file in glob.glob("*.y*ml"):
            with open(yaml_file) as f:
                yaml_contents = f.read()
            migration_yamls.append((yaml_file, yaml_contents))

    # TODO: use the inbuilt LUT in the graph
    output_to_feedstock = {
        output: name
        for name, node in gx.nodes.items()
        for output in node.get("payload", {}).get("outputs_names", [])
    }
    all_package_names = set(gx.nodes) | set(
        sum(
            [
                node.get("payload", {}).get("outputs_names", [])
                for node in gx.nodes.values()
            ],
            [],
        )
    )
    for yaml_file, yaml_contents in migration_yamls:
        loaded_yaml = yaml.safe_load(yaml_contents)
        print(os.path.splitext(yaml_file)[0])

        migrator_config = loaded_yaml.get("__migrator", {})
        excluded_feedstocks = set(migrator_config.get("exclude", []))
        pr_limit = min(migrator_config.pop("pr_limit", pr_limit), pr_limit)

        package_names = (
            (set(loaded_yaml) | {l.replace("_", "-") for l in loaded_yaml})
            & all_package_names
        ) - excluded_feedstocks

        add_rebuild_migration_yaml(
            migrators=migrators,
            gx=gx,
            package_names=list(package_names),
            output_to_feedstock=output_to_feedstock,
            excluded_feedstocks=excluded_feedstocks,
            migration_yaml=yaml_contents,
            migration_name=os.path.splitext(yaml_file)[0],
            config=migrator_config,
            pr_limit=pr_limit,
        )


def _outside_pin_range(pin_spec, current_pin, new_version):
    pin_level = len(pin_spec.split("."))
    current_split = current_pin.split(".")
    new_split = new_version.split(".")
    # if our pin spec is more exact than our current pin then rebuild more precisely
    if pin_level > len(current_split):
        return True
    for i in range(pin_level):
        if current_split[i] != new_split[i]:
            return True
    return False


def create_migration_yaml_creator(migrators: MutableSequence[Migrator], gx: nx.DiGraph):
    with indir(os.environ["CONDA_PREFIX"]):
        pinnings = parse_config_file(
            "conda_build_config.yaml", config=Config(**CB_CONFIG)
        )
    feedstocks_to_be_repinned = []
    for k, package_pin_list in pinnings.items():
        # we need the package names for the migrator itself but need the
        # feedstock for everything else
        package_name = k
        # exclude non-package keys
        if k not in gx.nodes and k not in gx.graph["outputs_lut"]:
            # conda_build_config.yaml can't have `-` unlike our package names
            k = k.replace("_", "-")
        # replace sub-packages with their feedstock names
        k = gx.graph["outputs_lut"].get(k, k)

        if (
            (k in gx.nodes)
            and not gx.nodes[k]["payload"].get("archived", False)
            and gx.nodes[k]["payload"].get("version")
            and k not in feedstocks_to_be_repinned
        ):

            current_pins = list(map(str, package_pin_list))
            current_version = str(gx.nodes[k]["payload"]["version"])

            # we need a special parsing for pinning stuff
            meta_yaml = parse_meta_yaml(
                gx.nodes[k]["payload"]["raw_meta_yaml"],
                for_pinning=True,
            )

            # find the most stringent max pin for this feedstock if any
            pin_spec = ""
            for block in [meta_yaml] + meta_yaml.get("outputs", []) or []:
                build = block.get("build", {}) or {}
                # and check the exported package is within the feedstock
                exports = [
                    p.get("max_pin", "")
                    for p in build.get("run_exports", [{}])
                    # make certain not direct hard pin
                    if isinstance(p, MutableMapping)
                    # if the pinned package is in an output of the parent feedstock
                    and (
                        gx.graph["outputs_lut"].get(p.get("package_name", ""), "") == k
                        # if the pinned package is the feedstock itself
                        or p.get("package_name", "") == k
                    )
                ]
                if not exports:
                    continue
                # get the most stringent pin spec from the recipe block
                max_pin = max(exports, key=len)
                if len(max_pin) > len(pin_spec):
                    pin_spec = max_pin

            # fall back to the pinning file or "x"
            if not pin_spec:
                pin_spec = (
                    pinnings["pin_run_as_build"].get(k, {}).get("max_pin", "x") or "x"
                )

            current_pins = list(
                map(lambda x: re.sub("[^0-9.]", "", x).rstrip("."), current_pins)
            )
            current_version = re.sub("[^0-9.]", "", current_version).rstrip(".")
            if current_pins == [""]:
                continue

            current_pin = str(max(map(VersionOrder, current_pins)))
            # If the current pin and the current version is the same nothing
            # to do even if the pin isn't accurate to the spec
            if current_pin != current_version and _outside_pin_range(
                pin_spec, current_pin, current_version
            ):
                feedstocks_to_be_repinned.append(k)
                print(package_name, current_version, current_pin, pin_spec)
                migrators.append(
                    MigrationYamlCreator(
                        package_name, current_version, current_pin,
                        pin_spec,
                    )
                )


def initialize_migrators(
    github_username: str = "",
    github_password: str = "",
    github_token: Optional[str] = None,
    dry_run: bool = False,
) -> Tuple[MigratorSessionContext, list, MutableSequence[Migrator]]:
    temp = glob.glob("/tmp/*")
    gx = load_graph()
    smithy_version = eval_xonsh("conda smithy --version")
    pinning_version = json.loads(eval_xonsh("conda list conda-forge-pinning --json"))[
        0
    ]["version"]

    add_arch_migrate(MIGRATORS, gx)
    migration_factory(MIGRATORS, gx)
    add_replacement_migrator(
        MIGRATORS,
        gx,
        "matplotlib",
        "matplotlib-base",
        ("Unless you need `pyqt`, recipes should depend only on " "`matplotlib-base`."),
        alt_migrator=MatplotlibBase,
    )
    create_migration_yaml_creator(migrators=MIGRATORS, gx=gx)
    for m in MIGRATORS:
        print(f'{getattr(m, "name", m)} graph size: {len(getattr(m, "graph", []))}')

    ctx = MigratorSessionContext(
        circle_build_url=os.getenv("CIRCLE_BUILD_URL", ""),
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

    gv = graphviz.Digraph(graph_attr={"packmode": "array_3"})
    for node, node_attrs in gx2.nodes.items():
        attrs = node_attrs["payload"]
        # remove archived from status
        if attrs.get("archived", False):
            continue
        node_metadata: Dict = {}
        feedstock_metadata[node] = node_metadata
        nuid = migrator.migrator_uid(attrs)
        all_pr_jsons = []
        for pr_json in attrs.get("PRed", []):
            all_pr_jsons.append(copy.deepcopy(pr_json))

        # hack around bug in migrator vs graph data for this one
        if isinstance(migrator, MatplotlibBase):
            if "name" in nuid:
                del nuid["name"]
            for i in range(len(all_pr_jsons)):
                if (
                    all_pr_jsons[i]
                    and "name" in all_pr_jsons[i]["data"]
                    and all_pr_jsons[i]["data"]["migrator_name"] == "MatplotlibBase"
                ):
                    del all_pr_jsons[i]["data"]["name"]

        for pr_json in all_pr_jsons:
            if pr_json and pr_json["data"] == frozen_to_json_friendly(nuid)["data"]:
                break
        else:
            pr_json = None

        # No PR was ever issued but the migration was performed.
        # This is only the case when the migration was done manually
        # before the bot could issue any PR.
        manually_done = pr_json is None and frozen_to_json_friendly(nuid)["data"] in (
            z["data"] for z in all_pr_jsons
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
            elif not isinstance(migrator, Replacement):
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
                URL=(pr_json or {}).get("PR", {}).get("html_url", ""),
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
    # logging
    from .xonsh_utils import env

    debug = env.get("CONDA_FORGE_TICK_DEBUG", False)
    if debug:
        setup_logger(logging.getLogger("conda_forge_tick"), level="debug")
    else:
        setup_logger(logging.getLogger("conda_forge_tick"))

    github_username = env.get("USERNAME", "")
    github_password = env.get("PASSWORD", "")
    github_token = env.get("GITHUB_TOKEN")
    global MIGRATORS
    mctx, temp, MIGRATORS = initialize_migrators(
        github_username=github_username,
        github_password=github_password,
        dry_run=args.dry_run,
        github_token=github_token,
    )

    time_per = float(env.get("TIMEOUT", 600)) / len(MIGRATORS)

    for migrator in MIGRATORS:

        mmctx = MigratorContext(session=mctx, migrator=migrator)
        migrator.bind_to_ctx(mmctx)

        good_prs = 0
        _mg_start = time.time()
        effective_graph = mmctx.effective_graph

        if hasattr(migrator, "name"):
            extra_name = "-%s" % migrator.name
        else:
            extra_name = ""

        logger.info(
            "Total migrations for %s%s: %d",
            migrator.__class__.__name__,
            extra_name,
            len(effective_graph.nodes),
        )

        for node_name in migrator.order(effective_graph, mctx.graph):
            with mctx.graph.nodes[node_name]["payload"] as attrs:
                # Don't let CI timeout, break ahead of the timeout so we make certain
                # to write to the repo
                # TODO: convert these env vars
                _now = time.time()
                if (
                    (
                        _now - int(env.get("START_TIME", time.time())) >
                        int(env.get("TIMEOUT", 600))
                    ) or
                    good_prs >= migrator.pr_limit or
                    (_now - _mg_start) > time_per
                ):
                    break

                fctx = FeedstockContext(
                    package_name=node_name,
                    feedstock_name=attrs["feedstock_name"],
                    attrs=attrs,
                )

                logger.info(
                    "%s%s IS MIGRATING %s",
                    migrator.__class__.__name__.upper(),
                    extra_name,
                    fctx.package_name,
                )
                try:
                    # Don't bother running if we are at zero
                    if (
                        args.dry_run
                        or mctx.gh.rate_limit()["resources"]["core"]["remaining"] == 0
                    ):
                        break
                    migrator_uid, pr_json = run(
                        feedstock_ctx=fctx,
                        migrator=migrator,
                        rerender=migrator.rerender,
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
                            d["PR"] = pr_json
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
                    if not args.dry_run:
                        dump_graph(mctx.graph)

                    eval_xonsh(f"rm -rf {mctx.rever_dir}/*")
                    logger.info(os.getcwd())
                    for f in glob.glob("/tmp/*"):
                        if f not in temp:
                            eval_xonsh(f"rm -rf {f}")

    if not args.dry_run:
        logger.info(
            "API Calls Remaining: %d",
            mctx.gh.rate_limit()["resources"]["core"]["remaining"],
        )
    logger.info("Done")


if __name__ == "__main__":
    pass  # main()
