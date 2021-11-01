import copy
import glob
import json
import re
import sys

import time
import traceback
import logging
import os
import typing
import tqdm
from subprocess import CalledProcessError
from typing import (
    Optional,
    MutableSequence,
    MutableSet,
    Sequence,
    Tuple,
    Set,
    Mapping,
    MutableMapping,
    Union,
)

if typing.TYPE_CHECKING:
    from .cli import CLIArgs
    from .migrators_types import (
        MetaYamlTypedDict,
        PackageName,
        MigrationUidTypedDict,
    )

# from conda_forge_tick.profiler import profiling

import networkx as nx
from conda.models.version import VersionOrder
from conda_build.config import Config
from conda_build.variants import parse_config_file

from urllib.error import URLError

import github3
from uuid import uuid4

from conda_forge_tick.xonsh_utils import indir, env

from conda_forge_tick.contexts import (
    FeedstockContext,
    MigratorSessionContext,
    MigratorContext,
)
from conda_forge_tick.git_utils import (
    get_repo,
    push_repo,
    is_github_api_limit_reached,
    comment_on_pr,
)
from conda_forge_tick.utils import (
    setup_logger,
    pluck,
    load_graph,
    dump_graph,
    LazyJson,
    CB_CONFIG,
    parse_meta_yaml,
    eval_cmd,
    sanitize_string,
    frozen_to_json_friendly,
    yaml_safe_load,
)
from conda_forge_tick.migrators.arch import OSXArm
from conda_forge_tick.migrators.migration_yaml import (
    MigrationYamlCreator,
    create_rebuild_graph,
)
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
    Jinja2VarsCleanup,
    UpdateConfigSubGuessMigrator,
    UpdateCMakeArgsMigrator,
    GuardTestingMigrator,
    CrossRBaseMigrator,
    CrossPythonMigrator,
    Build2HostMigrator,
    NoCondaInspectMigrator,
    DuplicateLinesCleanup,
    Cos7Config,
    PipWheelMigrator,
    RebuildBroken,
    GraphMigrator,
)

from conda_forge_tick.mamba_solver import is_recipe_solvable

LOGGER = logging.getLogger("conda_forge_tick.auto_tick")

PR_LIMIT = 5
MAX_PR_LIMIT = 50

BOT_RERUN_LABEL = {
    "name": "bot-rerun",
    "color": "#191970",
    "description": (
        "Apply this label if you want the bot to retry "
        "issuing a particular pull-request"
    ),
}


def run(
    feedstock_ctx: FeedstockContext,
    migrator: Migrator,
    protocol: str = "ssh",
    pull_request: bool = True,
    rerender: bool = True,
    fork: bool = True,
    base_branch: str = "main",
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
    base_branch : str, optional
        The base branch to which the PR will be targeted. Defaults to "master".
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

    branch_name = migrator.remote_branch(feedstock_ctx) + "_h" + uuid4().hex[0:6]

    if hasattr(migrator, "name"):
        assert isinstance(migrator.name, str)
        migrator_name = migrator.name.lower().replace(" ", "")
    else:
        migrator_name = migrator.__class__.__name__.lower()

    # TODO: run this in parallel
    feedstock_dir, repo = get_repo(
        ctx=migrator.ctx.session,
        fctx=feedstock_ctx,
        branch=branch_name,
        feedstock=feedstock_ctx.feedstock_name,
        protocol=protocol,
        pull_request=pull_request,
        fork=fork,
        base_branch=base_branch,
    )
    if not feedstock_dir or not repo:
        LOGGER.critical(
            "Failed to migrate %s, %s",
            feedstock_ctx.package_name,
            feedstock_ctx.attrs.get("bad"),
        )
        return False, False

    recipe_dir = os.path.join(feedstock_dir, "recipe")

    # migrate the feedstock
    migrator.run_pre_piggyback_migrations(recipe_dir, feedstock_ctx.attrs, **kwargs)

    # TODO - make a commit here if the repo changed

    migrate_return = migrator.migrate(recipe_dir, feedstock_ctx.attrs, **kwargs)

    if not migrate_return:
        LOGGER.critical(
            "Failed to migrate %s, %s",
            feedstock_ctx.package_name,
            feedstock_ctx.attrs.get("bad"),
        )
        eval_cmd(f"rm -rf {feedstock_dir}")
        return False, False

    # TODO - commit main migration here

    migrator.run_post_piggyback_migrations(recipe_dir, feedstock_ctx.attrs, **kwargs)

    # TODO commit post migration here

    # rerender, maybe
    diffed_files: typing.List[str] = []
    with indir(feedstock_dir), env.swap(RAISE_SUBPROC_ERROR=False):
        msg = migrator.commit_message(feedstock_ctx)  # noqa
        try:
            eval_cmd("git add --all .")
            if migrator.allow_empty_commits:
                eval_cmd(f"git commit --allow-empty -am '{msg}'")
            else:
                eval_cmd(f"git commit -am '{msg}'")
        except CalledProcessError as e:
            LOGGER.info(
                "could not commit to feedstock - "
                "likely no changes - error is '%s'" % (repr(e)),
            )
            # we bail here if we do not plan to rerender and we wanted an empty
            # commit
            # this prevents PRs that don't actually get made from getting marked as done
            if migrator.allow_empty_commits and not rerender:
                raise e

        if rerender:
            head_ref = eval_cmd("git rev-parse HEAD").strip()
            LOGGER.info("Rerendering the feedstock")

            try:
                eval_cmd(
                    "conda smithy rerender -c auto --no-check-uptodate",
                    timeout=300,
                )
                make_rerender_comment = False
            except Exception as e:
                # I am trying this bit of code to force these errors
                # to be surfaced in the logs at the right time.
                print(f"RERENDER ERROR: {e}", flush=True)
                if not isinstance(migrator, Version):
                    raise
                else:
                    # for check solvable or automerge, we always raise rerender errors
                    if feedstock_ctx.attrs["conda-forge.yml"].get("bot", {}).get(
                        "check_solvable",
                        False,
                    ) or (
                        feedstock_ctx.attrs["conda-forge.yml"]
                        .get("bot", {})
                        .get(
                            "automerge",
                            False,
                        )
                    ):
                        raise
                    else:
                        make_rerender_comment = True

            # If we tried to run the MigrationYaml and rerender did nothing (we only
            # bumped the build number and dropped a yaml file in migrations) bail
            # for instance platform specific migrations
            gdiff = eval_cmd(f"git diff --name-only {head_ref.strip()}...HEAD")

            diffed_files = [
                _
                for _ in gdiff.split()
                if not (
                    _.startswith("recipe")
                    or _.startswith("migrators")
                    or _.startswith("README")
                )
            ]
        else:
            make_rerender_comment = False

    if (
        feedstock_ctx.feedstock_name != "conda-forge-pinning"
        and (base_branch == "master" or base_branch == "main")
        and (
            (
                migrator.check_solvable
                # we always let stuff in cycles go
                and feedstock_ctx.attrs["name"]
                not in getattr(migrator, "cycles", set())
                # we always let stuff at the top go
                and feedstock_ctx.attrs["name"]
                not in getattr(migrator, "top_level", set())
            )
            or feedstock_ctx.attrs["conda-forge.yml"]
            .get("bot", {})
            .get(
                "check_solvable",
                False,
            )
        )
    ):
        solvable, errors, _ = is_recipe_solvable(
            feedstock_dir,
            build_platform=feedstock_ctx.attrs["conda-forge.yml"].get(
                "build_platform",
                None,
            ),
        )
        pre_key = "pre_pr_migrator_status"
        if not solvable:
            _solver_err_str = "not solvable ({}): {}: {}".format(
                ('<a href="' + os.getenv("CIRCLE_BUILD_URL", "") + '">bot CI job</a>'),
                base_branch,
                sorted(set(errors)),
            )

            if isinstance(migrator, Version):
                _new_ver = feedstock_ctx.attrs["new_version"]
                feedstock_ctx.attrs["new_version_errors"][_new_ver] = _solver_err_str
                feedstock_ctx.attrs["new_version_errors"][_new_ver] = sanitize_string(
                    feedstock_ctx.attrs["new_version_errors"][_new_ver],
                )
                # remove part of a try for solver errors to make those slightly
                # higher priority
                feedstock_ctx.attrs["new_version_attempts"][_new_ver] -= 0.8

            if pre_key not in feedstock_ctx.attrs:
                feedstock_ctx.attrs[pre_key] = {}
            feedstock_ctx.attrs[pre_key][migrator_name] = sanitize_string(
                _solver_err_str,
            )
            eval_cmd(f"rm -rf {feedstock_dir}")
            return False, False
        else:
            if (
                pre_key in feedstock_ctx.attrs
                and migrator_name in feedstock_ctx.attrs[pre_key]
            ):
                feedstock_ctx.attrs[pre_key].pop(migrator_name)

    # TODO: Better annotation here
    pr_json: typing.Union[MutableMapping, None, bool]
    if (
        isinstance(migrator, MigrationYaml)
        and not diffed_files
        and feedstock_ctx.attrs["name"] != "conda-forge-pinning"
    ):
        # spoof this so it looks like the package is done
        pr_json = {
            "state": "closed",
            "merged_at": "never issued",
            "id": str(uuid4()),
        }
    else:
        # push up
        try:
            # TODO: remove this hack, but for now this is the only way to get
            # the feedstock dir into pr_body
            feedstock_ctx.feedstock_dir = feedstock_dir
            pr_json = push_repo(
                session_ctx=migrator.ctx.session,
                fctx=feedstock_ctx,
                feedstock_dir=feedstock_dir,
                body=migrator.pr_body(feedstock_ctx),
                repo=repo,
                title=migrator.pr_title(feedstock_ctx),
                head=f"{migrator.ctx.github_username}:{branch_name}",
                branch=branch_name,
                base_branch=base_branch,
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

    if pr_json and pr_json["state"] != "closed" and make_rerender_comment:
        comment_on_pr(
            pr_json,
            """\
Hi! This feedstock was not able to be rerendered after the version update changes. I
have pushed the version update changes anyways and am trying to rerender again with this
comment. Hopefully you all can fix this!

@conda-forge-admin rerender""",
            repo,
        )

    if pr_json:
        ljpr = LazyJson(
            os.path.join(migrator.ctx.session.prjson_dir, str(pr_json["id"]) + ".json"),
        )
        ljpr.update(**pr_json)

        # from .dynamo_models import PRJson
        # PRJson.dump(pr_json)
    else:
        ljpr = False

    # If we've gotten this far then the node is good
    feedstock_ctx.attrs["bad"] = False
    LOGGER.info("Removing feedstock dir")
    eval_cmd(f"rm -rf {feedstock_dir}")
    return migrate_return, ljpr


def _host_run_test_dependencies(meta_yaml: "MetaYamlTypedDict") -> Set["PackageName"]:
    """Parse the host/run/test dependencies of a recipe

    This function parses top-level and `outputs` requirements sections.

    The complicated logic here is mainly to support not including a
    `host` section, and using `build` instead.
    """
    _ = meta_yaml["requirements"]
    rq = (_["host"] or _["build"]) | _["run"] | _["test"]
    return typing.cast("Set[PackageName]", rq)


def add_rebuild_broken_migrator(
    migrators: MutableSequence[Migrator],
    gx: nx.DiGraph,
):
    migrators.append(
        RebuildBroken(
            outputs_lut=gx.graph["outputs_lut"],
            pr_limit=PR_LIMIT,
        ),
    )


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
    print(
        "========================================"
        "========================================",
        flush=True,
    )
    print(f"making replacement migrator for {old_pkg} -> {new_pkg}", flush=True)
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
    print(
        "========================================"
        "========================================",
        flush=True,
    )
    print("making aarch64+ppc64le and osx-arm64 migrations", flush=True)
    total_graph = copy.deepcopy(gx)

    migrators.append(
        ArchRebuild(
            graph=total_graph,
            pr_limit=PR_LIMIT,
            name="aarch64 and ppc64le addition",
        ),
    )
    migrators.append(
        OSXArm(
            graph=total_graph,
            pr_limit=PR_LIMIT,
            name="arm osx addition",
            piggy_back_migrations=[
                Build2HostMigrator(),
                UpdateConfigSubGuessMigrator(),
                CondaForgeYAMLCleanup(),
                UpdateCMakeArgsMigrator(),
                GuardTestingMigrator(),
                CrossRBaseMigrator(),
                CrossPythonMigrator(),
                NoCondaInspectMigrator(),
            ],
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

    total_graph = create_rebuild_graph(
        gx,
        package_names,
        excluded_feedstocks,
        include_noarch=config.get("include_noarch", False),
    )

    # Note at this point the graph is made of all packages that have a
    # dependency on the pinned package via Host, run, or test.
    # Some packages don't have a host section so we use their
    # build section in its place.

    feedstock_names = set()
    for p in package_names:
        feedstock_names |= output_to_feedstock.get(p, {p})

    feedstock_names = {
        p for p in feedstock_names if p in gx.nodes
    } - excluded_feedstocks

    top_level = {
        node
        for node in {
            gx.successors(feedstock_name) for feedstock_name in feedstock_names
        }
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
            Jinja2VarsCleanup(),
            DuplicateLinesCleanup(),
            PipMigrator(),
            LicenseMigrator(),
            CondaForgeYAMLCleanup(),
            ExtraJinja2KeysCleanup(),
            Build2HostMigrator(),
            NoCondaInspectMigrator(),
            Cos7Config(),
        ],
        **config,
    )
    print(f"migration yaml:\n {migration_yaml}", flush=True)
    print(f"bump number: {migrator.bump_number}\n", flush=True)
    migrators.append(migrator)


def migration_factory(
    migrators: MutableSequence[Migrator],
    gx: nx.DiGraph,
    pr_limit: int = PR_LIMIT,
    only_keep=None,
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

    if only_keep is None:
        only_keep = [
            os.path.splitext(os.path.basename(yaml_file))[0]
            for yaml_file, _ in migration_yamls
        ]

    output_to_feedstock = gx.graph["outputs_lut"]
    all_package_names = set(
        sum(
            (
                list(node.get("payload", {}).get("outputs_names", set()))
                for node in gx.nodes.values()
            ),
            [],
        ),
    )
    for yaml_file, yaml_contents in migration_yamls:
        loaded_yaml = yaml_safe_load(yaml_contents)
        __mname = os.path.splitext(os.path.basename(yaml_file))[0]

        if __mname not in only_keep:
            continue

        print(
            "========================================"
            "========================================\n"
            f"migrator: {__mname}",
            flush=True,
        )

        migrator_config = loaded_yaml.get("__migrator", {})
        paused = migrator_config.pop("paused", False)
        excluded_feedstocks = set(migrator_config.get("exclude", []))
        pr_limit = min(migrator_config.pop("pr_limit", pr_limit), MAX_PR_LIMIT)

        if "override_cbc_keys" in migrator_config:
            package_names = set(migrator_config.get("override_cbc_keys"))
        else:
            package_names = (
                set(loaded_yaml) | {ly.replace("_", "-") for ly in loaded_yaml}
            ) & all_package_names

        if not paused:
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
        else:
            LOGGER.warning("skipping migration %s because it is paused", __mname)


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
    cfp_gx = copy.deepcopy(gx)
    for node in list(cfp_gx.nodes):
        if node != "conda-forge-pinning":
            pluck(cfp_gx, node)

    print("pinning migrations", flush=True)
    with indir(os.environ["CONDA_PREFIX"]):
        pinnings = parse_config_file(
            "conda_build_config.yaml",
            config=Config(**CB_CONFIG),
        )
    feedstocks_to_be_repinned = []
    for pinning_name, package_pin_list in pinnings.items():
        # there are three things:
        # pinning_name - entry in pinning file
        # package_name - the actual package, could differ via `-` -> `_`
        #                from pinning_name
        # feedstock_name - the feedstock that outputs the package
        # we need the package names for the migrator itself but need the
        # feedstock for everything else

        # exclude non-package keys
        if pinning_name not in gx.graph["outputs_lut"]:
            # conda_build_config.yaml can't have `-` unlike our package names
            package_name = pinning_name.replace("_", "-")
        else:
            package_name = pinning_name

        # replace sub-packages with their feedstock names
        # TODO - we are grabbing one element almost at random here
        # the sorted call makes it stable at least?
        fs_name = next(
            iter(
                sorted(gx.graph["outputs_lut"].get(package_name, {package_name})),
            ),
        )

        if (
            (fs_name in gx.nodes)
            and not gx.nodes[fs_name]["payload"].get("archived", False)
            and gx.nodes[fs_name]["payload"].get("version")
            and fs_name not in feedstocks_to_be_repinned
        ):

            current_pins = list(map(str, package_pin_list))
            current_version = str(gx.nodes[fs_name]["payload"]["version"])

            try:
                # we need a special parsing for pinning stuff
                meta_yaml = parse_meta_yaml(
                    gx.nodes[fs_name]["payload"]["raw_meta_yaml"],
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
                        # ensure the export is for this package
                        and p.get("package_name", "") == package_name
                        # ensure the pinned package is in an output of the
                        # parent feedstock
                        and (
                            fs_name
                            in gx.graph["outputs_lut"].get(
                                p.get("package_name", ""),
                                set(),
                            )
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
                        pinnings["pin_run_as_build"]
                        .get(pinning_name, {})
                        .get("max_pin", "x")
                    ) or "x"

                current_pins = list(
                    map(lambda x: re.sub("[^0-9.]", "", x).rstrip("."), current_pins),
                )
                current_pins = [cp.strip() for cp in current_pins if cp.strip() != ""]
                current_version = re.sub("[^0-9.]", "", current_version).rstrip(".")
                if not current_pins or current_version == "":
                    continue

                current_pin = str(max(map(VersionOrder, current_pins)))
                # If the current pin and the current version is the same nothing
                # to do even if the pin isn't accurate to the spec
                if current_pin != current_version and _outside_pin_range(
                    pin_spec,
                    current_pin,
                    current_version,
                ):
                    feedstocks_to_be_repinned.append(fs_name)
                    print(
                        "    %s:\n"
                        "        curr version: %s\n"
                        "        curr pin: %s\n"
                        "        pin_spec: %s"
                        % (pinning_name, current_version, current_pin, pin_spec),
                        flush=True,
                    )
                    migrators.append(
                        MigrationYamlCreator(
                            pinning_name,
                            current_version,
                            current_pin,
                            pin_spec,
                            fs_name,
                            cfp_gx,
                            full_graph=gx,
                        ),
                    )
            except Exception as e:
                LOGGER.info(
                    "failed to possibly generate pinning PR for {}: {}".format(
                        pinning_name,
                        repr(e),
                    ),
                )
                continue
    print(" ", flush=True)


def initialize_migrators(
    github_username: str = "",
    github_password: str = "",
    github_token: Optional[str] = None,
    dry_run: bool = False,
) -> Tuple[MigratorSessionContext, list, MutableSequence[Migrator]]:
    temp = glob.glob("/tmp/*")
    gx = load_graph()
    smithy_version = eval_cmd("conda smithy --version").strip()
    pinning_version = json.loads(eval_cmd("conda list conda-forge-pinning --json"))[0][
        "version"
    ]

    migrators = []

    add_rebuild_broken_migrator(migrators, gx)
    add_arch_migrate(migrators, gx)
    migration_factory(migrators, gx)
    add_replacement_migrator(
        migrators,
        gx,
        "matplotlib",
        "matplotlib-base",
        ("Unless you need `pyqt`, recipes should depend only on " "`matplotlib-base`."),
        alt_migrator=MatplotlibBase,
    )
    create_migration_yaml_creator(migrators=migrators, gx=gx)
    print("rebuild migration graph sizes:", flush=True)
    for m in migrators:
        if isinstance(m, GraphMigrator):
            print(
                f'    {getattr(m, "name", m)} graph size: '
                f'{len(getattr(m, "graph", []))}',
                flush=True,
            )
    print(" ", flush=True)

    mctx = MigratorSessionContext(
        circle_build_url=os.getenv("CIRCLE_BUILD_URL", ""),
        graph=gx,
        smithy_version=smithy_version,
        pinning_version=pinning_version,
        github_username=github_username,
        github_password=github_password,
        github_token=github_token,
        dry_run=dry_run,
    )

    print("building package import maps and version migrator", flush=True)
    python_nodes = {
        n for n, v in mctx.graph.nodes("payload") if "python" in v.get("req", "")
    }
    python_nodes.update(
        [
            k
            for node_name, node in mctx.graph.nodes("payload")
            for k in node.get("outputs_names", [])
            if node_name in python_nodes
        ],
    )
    version_migrator = Version(
        python_nodes=python_nodes,
        pr_limit=PR_LIMIT * 4,
        piggy_back_migrations=[
            Jinja2VarsCleanup(),
            DuplicateLinesCleanup(),
            PipMigrator(),
            LicenseMigrator(),
            CondaForgeYAMLCleanup(),
            ExtraJinja2KeysCleanup(),
            Build2HostMigrator(),
            NoCondaInspectMigrator(),
            Cos7Config(),
            PipWheelMigrator(),
        ],
    )

    migrators = [version_migrator] + migrators

    print(" ", flush=True)

    return mctx, temp, migrators


def _compute_time_per_migrator(mctx, migrators):
    # we weight each migrator by the number of available nodes to migrate
    num_nodes = []
    for migrator in tqdm.tqdm(migrators):
        mmctx = MigratorContext(session=mctx, migrator=migrator)
        migrator.bind_to_ctx(mmctx)

        if isinstance(migrator, Version):
            _num_nodes = 0
            for node_name in mmctx.effective_graph.nodes:
                with mmctx.effective_graph.nodes[node_name]["payload"] as attrs:
                    _attempts = attrs.get("new_version_attempts", {}).get(
                        attrs.get("new_version", ""),
                        0,
                    )
                    if _attempts < 3:
                        _num_nodes += 1
            _num_nodes = max(
                _num_nodes,
                min(PR_LIMIT * 4, len(mmctx.effective_graph.nodes)),
            )
            num_nodes.append(_num_nodes)
        else:
            num_nodes.append(len(mmctx.effective_graph.nodes))

    num_nodes_tot = sum(num_nodes)
    # do not divide by zero
    time_per_node = float(env.get("TIMEOUT", 600)) / max(num_nodes_tot, 1)

    # also enforce a minimum of 300 seconds if any nodes can be migrated
    time_per_migrator = []
    for i, migrator in enumerate(migrators):
        _time_per = num_nodes[i] * time_per_node

        if num_nodes[i] > 0 and _time_per < 300:
            _time_per = 300

        time_per_migrator.append(_time_per)

    # finally rescale to fit in the time we have
    tot_time_per_migrator = sum(time_per_migrator)
    if tot_time_per_migrator > 0:
        time_fac = float(env.get("TIMEOUT", 600)) / tot_time_per_migrator
    else:
        time_fac = 1.0
    for i in range(len(time_per_migrator)):
        time_per_migrator[i] = time_per_migrator[i] * time_fac

    # recompute the total here
    tot_time_per_migrator = sum(time_per_migrator)

    return num_nodes, time_per_migrator, tot_time_per_migrator


# @profiling
def main(args: "CLIArgs") -> None:

    # logging
    if args.debug:
        setup_logger(logging.getLogger("conda_forge_tick"), level="debug")
    else:
        setup_logger(logging.getLogger("conda_forge_tick"))

    github_username = env.get("USERNAME", "")
    github_password = env.get("PASSWORD", "")
    github_token = env.get("GITHUB_TOKEN")

    mctx, temp, migrators = initialize_migrators(
        github_username=github_username,
        github_password=github_password,
        dry_run=args.dry_run,
        github_token=github_token,
    )

    # compute the time per migrator
    print("computing time per migration", flush=True)
    (num_nodes, time_per_migrator, tot_time_per_migrator) = _compute_time_per_migrator(
        mctx,
        migrators,
    )
    for i, migrator in enumerate(migrators):
        if hasattr(migrator, "name"):
            extra_name = "-%s" % migrator.name
        else:
            extra_name = ""

        print(
            "    %s%s: %d - gets %f seconds (%f percent)"
            % (
                migrator.__class__.__name__,
                extra_name,
                num_nodes[i],
                time_per_migrator[i],
                time_per_migrator[i] / max(tot_time_per_migrator, 1) * 100,
            ),
            flush=True,
        )

    for mg_ind, migrator in enumerate(migrators):
        if hasattr(migrator, "name"):
            assert isinstance(migrator.name, str)
            migrator_name = migrator.name.lower().replace(" ", "")
        else:
            migrator_name = migrator.__class__.__name__.lower()

        mmctx = MigratorContext(session=mctx, migrator=migrator)
        migrator.bind_to_ctx(mmctx)

        good_prs = 0
        _mg_start = time.time()
        effective_graph = mmctx.effective_graph
        time_per = time_per_migrator[mg_ind]

        if hasattr(migrator, "name"):
            extra_name = "-%s" % migrator.name
        else:
            extra_name = ""

        print(
            "\n========================================"
            "========================================"
            "\n"
            "========================================"
            "========================================",
            flush=True,
        )
        print(
            "Running migrations for %s%s: %d\n"
            % (
                migrator.__class__.__name__,
                extra_name,
                len(effective_graph.nodes),
            ),
            flush=True,
        )

        possible_nodes = list(migrator.order(effective_graph, mctx.graph))

        # version debugging info
        if isinstance(migrator, Version):
            LOGGER.info("possible version migrations:")
            for node_name in possible_nodes:
                with effective_graph.nodes[node_name]["payload"] as attrs:
                    LOGGER.info(
                        "    node|curr|new|attempts: %s|%s|%s|%f",
                        node_name,
                        attrs.get("version"),
                        attrs.get("new_version"),
                        (
                            attrs.get("new_version_attempts", {}).get(
                                attrs.get("new_version", ""),
                                0,
                            )
                        ),
                    )

        for node_name in possible_nodes:
            with mctx.graph.nodes[node_name]["payload"] as attrs:
                # Don't let CI timeout, break ahead of the timeout so we make certain
                # to write to the repo
                # TODO: convert these env vars
                _now = time.time()
                if (
                    (
                        _now - int(env.get("START_TIME", time.time()))
                        > int(env.get("TIMEOUT", 600))
                    )
                    or good_prs >= migrator.pr_limit
                    or (_now - _mg_start) > time_per
                ):
                    break

                base_branches = migrator.get_possible_feedstock_branches(attrs)
                if "branch" in attrs:
                    has_attrs_branch = True
                    orig_branch = attrs.get("branch")
                else:
                    has_attrs_branch = False
                    orig_branch = None

                fctx = FeedstockContext(
                    package_name=node_name,
                    feedstock_name=attrs["feedstock_name"],
                    attrs=attrs,
                )

                # map main to current default branch
                base_branches = [
                    br if br != "main" else fctx.default_branch for br in base_branches
                ]

                try:
                    for base_branch in base_branches:
                        attrs["branch"] = base_branch
                        if migrator.filter(attrs):
                            continue

                        print("\n", flush=True, end="")
                        sys.stderr.flush()
                        sys.stdout.flush()
                        LOGGER.info(
                            "%s%s IS MIGRATING %s:%s",
                            migrator.__class__.__name__.upper(),
                            extra_name,
                            fctx.package_name,
                            base_branch,
                        )
                        try:
                            # Don't bother running if we are at zero
                            if mctx.gh_api_requests_left == 0:
                                break
                            migrator_uid, pr_json = run(
                                feedstock_ctx=fctx,
                                migrator=migrator,
                                rerender=migrator.rerender,
                                protocol="https",
                                hash_type=attrs.get("hash_type", "sha256"),
                                base_branch=base_branch,
                            )
                            # if migration successful
                            if migrator_uid:
                                d = frozen_to_json_friendly(migrator_uid)
                                # if we have the PR already do nothing
                                if d["data"] in [
                                    existing_pr["data"]
                                    for existing_pr in attrs.get("PRed", [])
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
                                LOGGER.critical(
                                    "GITHUB ERROR ON FEEDSTOCK: %s",
                                    fctx.feedstock_name,
                                )
                                if is_github_api_limit_reached(e, mctx.gh):
                                    break
                        except URLError as e:
                            LOGGER.exception("URLError ERROR")
                            attrs["bad"] = {
                                "exception": str(e),
                                "traceback": str(traceback.format_exc()).split("\n"),
                                "code": getattr(e, "code"),
                                "url": getattr(e, "url"),
                            }

                            pre_key = "pre_pr_migrator_status"
                            if pre_key not in attrs:
                                attrs[pre_key] = {}
                            attrs[pre_key][migrator_name] = sanitize_string(
                                "bot error (%s): %s: %s"
                                % (
                                    '<a href="'
                                    + os.getenv("CIRCLE_BUILD_URL", "")
                                    + '">bot CI job</a>',
                                    base_branch,
                                    str(traceback.format_exc()),
                                ),
                            )
                        except Exception as e:
                            LOGGER.exception("NON GITHUB ERROR")
                            # we don't set bad for rerendering errors
                            if (
                                "conda smithy rerender -c auto --no-check-uptodate"
                                not in str(e)
                            ):
                                attrs["bad"] = {
                                    "exception": str(e),
                                    "traceback": str(traceback.format_exc()).split(
                                        "\n",
                                    ),
                                }

                            pre_key = "pre_pr_migrator_status"
                            if pre_key not in attrs:
                                attrs[pre_key] = {}
                            attrs[pre_key][migrator_name] = sanitize_string(
                                "bot error (%s): %s: %s"
                                % (
                                    '<a href="'
                                    + os.getenv("CIRCLE_BUILD_URL", "")
                                    + '">bot CI job</a>',
                                    base_branch,
                                    str(traceback.format_exc()),
                                ),
                            )
                        else:
                            if migrator_uid:
                                # On successful PR add to our counter
                                good_prs += 1
                finally:
                    # reset branch
                    if has_attrs_branch:
                        attrs["branch"] = orig_branch

                    # Write graph partially through
                    if not args.dry_run:
                        dump_graph(mctx.graph)

                    eval_cmd(f"rm -rf {mctx.rever_dir}/*")
                    LOGGER.info(os.getcwd())
                    for f in glob.glob("/tmp/*"):
                        if f not in temp:
                            try:
                                eval_cmd(f"rm -rf {f}")
                            except Exception:
                                pass

                if mctx.gh_api_requests_left == 0:
                    break

        print("\n", flush=True)

    LOGGER.info("API Calls Remaining: %d", mctx.gh_api_requests_left)
    LOGGER.info("Done")


if __name__ == "__main__":
    pass  # main()
