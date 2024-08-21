import copy
import glob
import logging
import os
import pprint
import random
import re
import time
import typing
from concurrent.futures import as_completed
from typing import (
    List,
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Sequence,
    Set,
    Union,
    cast,
)

if typing.TYPE_CHECKING:
    from .migrators_types import PackageName

import networkx as nx
import tqdm
from conda.models.version import VersionOrder
from conda_build.config import Config
from conda_build.variants import parse_config_file

from conda_forge_tick.cli_context import CliContext
from conda_forge_tick.executors import executor
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    get_all_keys_for_hashmap,
    lazy_json_override_backends,
    remove_key_for_hashmap,
)
from conda_forge_tick.migrators import (
    ArchRebuild,
    Build2HostMigrator,
    CondaForgeYAMLCleanup,
    CrossCompilationForARMAndPower,
    CrossPythonMigrator,
    CrossRBaseMigrator,
    DependencyUpdateMigrator,
    DuplicateLinesCleanup,
    ExtraJinja2KeysCleanup,
    GraphMigrator,
    GuardTestingMigrator,
    Jinja2VarsCleanup,
    JpegTurboMigrator,
    LibboostMigrator,
    LicenseMigrator,
    MigrationYaml,
    Migrator,
    MPIPinRunAsBuildCleanup,
    NoCondaInspectMigrator,
    Numpy2Migrator,
    PipMigrator,
    PipWheelMigrator,
    QtQtMainMigrator,
    Replacement,
    RUCRTCleanup,
    StdlibMigrator,
    UpdateCMakeArgsMigrator,
    UpdateConfigSubGuessMigrator,
    Version,
    make_from_lazy_json_data,
)
from conda_forge_tick.migrators.arch import OSXArm
from conda_forge_tick.migrators.migration_yaml import (
    MigrationYamlCreator,
    create_rebuild_graph,
)
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import (
    CB_CONFIG,
    fold_log_lines,
    load_existing_graph,
    parse_meta_yaml,
    parse_munged_run_export,
    pluck,
    yaml_safe_load,
)

# migrator runs on loop so avoid any seeds at current time should that happen
random.seed(os.urandom(64))

logger = logging.getLogger(__name__)

PR_LIMIT = 5
MAX_PR_LIMIT = 50
MAX_SOLVER_ATTEMPTS = 50
CHECK_SOLVABLE_TIMEOUT = 90  # 90 days


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
    alt_migrator : Replacement migrator or a subclass thereof
        An alternate Replacement migrator to use for special tasks.

    """
    with fold_log_lines(f"making replacement migrator for {old_pkg} -> {new_pkg}"):
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

    with fold_log_lines("making aarch64+ppc64le migrator"):
        migrators.append(
            ArchRebuild(
                graph=total_graph,
                pr_limit=PR_LIMIT,
                name="aarch64 and ppc64le addition",
            ),
        )

    with fold_log_lines("making osx-arm64 migrator"):
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
                    MPIPinRunAsBuildCleanup(),
                ],
            ),
        )


def add_rebuild_migration_yaml(
    migrators: MutableSequence[Migrator],
    gx: nx.DiGraph,
    package_names: Sequence[str],
    output_to_feedstock: Mapping[str, str],
    excluded_feedstocks: MutableSet[str],
    exclude_pinned_pkgs: bool,
    migration_yaml: str,
    config: dict,
    migration_name: str,
    nominal_pr_limit: int = PR_LIMIT,
    max_solver_attempts: int = 3,
    force_pr_after_solver_attempts: int = MAX_SOLVER_ATTEMPTS * 2,
    paused: bool = False,
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
    exclude_pinned_pkgs : bool
        Whether pinned packages should be excluded from the migration
    migration_yaml : str
        The raw yaml for the migration variant dict
    config: dict
        The __migrator contents of the migration
    migration_name: str
        Name of the migration
    nominal_pr_limit : int, optional
        The number of PRs per hour, defaults to 5
    force_pr_after_solver_attempts : int, optional
        The number of solver attempts after which to force a PR, defaults to 100.
    paused : bool, optional
        Whether the migration is paused, defaults to False.
    """

    total_graph = create_rebuild_graph(
        gx,
        package_names,
        excluded_feedstocks,
        exclude_pinned_pkgs=exclude_pinned_pkgs,
        include_noarch=config.get("include_noarch", False),
    )

    # Note at this point the graph is made of all packages that have a
    # dependency on the pinned package via Host, run, or test.
    # Some packages don't have a host section so we use their
    # build section in its place.

    feedstock_names: Set[str] = set()
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
    piggy_back_migrations = [
        Jinja2VarsCleanup(),
        DuplicateLinesCleanup(),
        PipMigrator(),
        LicenseMigrator(),
        CondaForgeYAMLCleanup(),
        ExtraJinja2KeysCleanup(),
        Build2HostMigrator(),
        NoCondaInspectMigrator(),
        CrossCompilationForARMAndPower(),
        MPIPinRunAsBuildCleanup(),
    ]
    if migration_name == "qt515":
        piggy_back_migrations.append(QtQtMainMigrator())
    if migration_name == "jpeg_to_libjpeg_turbo":
        piggy_back_migrations.append(JpegTurboMigrator())
    if migration_name == "boost_cpp_to_libboost":
        piggy_back_migrations.append(LibboostMigrator())
    if migration_name == "numpy2":
        piggy_back_migrations.append(Numpy2Migrator())
    if migration_name.startswith("r-base44"):
        piggy_back_migrations.append(RUCRTCleanup())
    # stdlib migrator runs on top of ALL migrations, see
    # https://github.com/conda-forge/conda-forge.github.io/issues/2102
    piggy_back_migrations.append(StdlibMigrator())
    cycles = set()
    for cyc in nx.simple_cycles(total_graph):
        cycles |= set(cyc)

    migrator = MigrationYaml(
        migration_yaml,
        name=migration_name,
        graph=total_graph,
        pr_limit=nominal_pr_limit,
        top_level=top_level,
        cycles=cycles,
        piggy_back_migrations=piggy_back_migrations,
        max_solver_attempts=max_solver_attempts,
        force_pr_after_solver_attempts=force_pr_after_solver_attempts,
        paused=paused,
        **config,
    )

    # adaptively set PR limits based on the number of PRs made so far
    number_pred = len(
        [
            k
            for k, v in migrator.graph.nodes.items()
            if migrator.migrator_uid(v.get("payload", {}))
            in [
                vv.get("data", {})
                for vv in v.get("payload", {}).get("pr_info", {}).get("PRed", [])
            ]
        ],
    )
    tot_nodes = len(migrator.graph.nodes)
    frac_pred = number_pred / tot_nodes

    tenth = int(tot_nodes / 10)
    quarter = int(tot_nodes / 4)
    half = int(tot_nodes / 2)
    three_quarters = int(tot_nodes * 0.75)
    number_pred_breaks = sorted(
        [0, 10, tenth, quarter, half, three_quarters, tot_nodes]
    )
    pr_limits = [
        min(2, nominal_pr_limit),
        nominal_pr_limit,
        min(int(nominal_pr_limit * 4), MAX_PR_LIMIT),
        min(int(nominal_pr_limit * 3), MAX_PR_LIMIT),
        min(int(nominal_pr_limit * 2), MAX_PR_LIMIT),
        min(int(nominal_pr_limit * 1.5), MAX_PR_LIMIT),
        min(nominal_pr_limit, MAX_PR_LIMIT),
    ]

    pr_limit = None
    for i, lim in enumerate(number_pred_breaks):
        if number_pred <= lim:
            pr_limit = pr_limits[i]
            break

    if pr_limit is None:
        pr_limit = nominal_pr_limit

    migrator.pr_limit = pr_limit

    print(f"migration yaml:\n{migration_yaml}", flush=True)
    print(f"bump number: {migrator.bump_number}", flush=True)
    print(
        f"# of PRs made so far: {number_pred} ({frac_pred * 100:0.2f} percent)",
        flush=True,
    )
    final_config = {}
    final_config.update(config)
    final_config["pr_limit"] = migrator.pr_limit
    final_config["max_solver_attempts"] = max_solver_attempts
    print("final config:\n", pprint.pformat(final_config) + "\n\n", flush=True)
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
    with pushd(migrations_loc):
        for yaml_file in sorted(glob.glob("*.y*ml")):
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

        with fold_log_lines(f"making {__mname} migrator"):
            migrator_config = loaded_yaml.get("__migrator", {})
            paused = migrator_config.pop("paused", False)
            excluded_feedstocks = set(migrator_config.get("exclude", []))
            _pr_limit = min(migrator_config.pop("pr_limit", pr_limit), MAX_PR_LIMIT)
            max_solver_attempts = min(
                migrator_config.pop("max_solver_attempts", 3),
                MAX_SOLVER_ATTEMPTS,
            )
            force_pr_after_solver_attempts = min(
                migrator_config.pop(
                    "force_pr_after_solver_attempts", MAX_SOLVER_ATTEMPTS * 2
                ),
                MAX_SOLVER_ATTEMPTS * 2,
            )

            if "override_cbc_keys" in migrator_config:
                package_names = set(migrator_config.get("override_cbc_keys"))
            else:
                package_names = (
                    set(loaded_yaml) | {ly.replace("_", "-") for ly in loaded_yaml}
                ) & all_package_names
            exclude_pinned_pkgs = migrator_config.get("exclude_pinned_pkgs", True)

            age = time.time() - loaded_yaml.get("migrator_ts", time.time())
            age /= 24 * 60 * 60
            print(
                "migrator %s is %d days old" % (__mname, int(age)),
                flush=True,
            )
            if (
                age > CHECK_SOLVABLE_TIMEOUT
                and "check_solvable" not in migrator_config
                and not migrator_config.get("longterm", False)
            ):
                migrator_config["check_solvable"] = False
                print(
                    "turning off solver checks for migrator "
                    "%s since over %d is over limit %d"
                    % (
                        __mname,
                        age,
                        CHECK_SOLVABLE_TIMEOUT,
                    ),
                    flush=True,
                )
                skip_solver_checks = True
            else:
                skip_solver_checks = False

            add_rebuild_migration_yaml(
                migrators=migrators,
                gx=gx,
                package_names=list(package_names),
                output_to_feedstock=output_to_feedstock,
                excluded_feedstocks=excluded_feedstocks,
                exclude_pinned_pkgs=exclude_pinned_pkgs,
                migration_yaml=yaml_contents,
                migration_name=os.path.splitext(yaml_file)[0],
                config=migrator_config,
                nominal_pr_limit=_pr_limit,
                max_solver_attempts=max_solver_attempts,
                force_pr_after_solver_attempts=force_pr_after_solver_attempts,
                paused=paused,
            )
            if skip_solver_checks:
                assert not migrators[-1].check_solvable

            if paused:
                print(f"skipping migration {__mname} because it is paused", flush=True)


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


def create_migration_yaml_creator(
    migrators: MutableSequence[Migrator], gx: nx.DiGraph, pin_to_debug=None
):
    cfp_gx = copy.deepcopy(gx)
    for node in list(cfp_gx.nodes):
        if node != "conda-forge-pinning":
            pluck(cfp_gx, node)

    with pushd(os.environ["CONDA_PREFIX"]):
        pinnings = parse_config_file(
            "conda_build_config.yaml",
            config=Config(**CB_CONFIG),
        )

        fname = "share/conda-forge/migration_support/packages_to_migrate_together.yaml"
        if os.path.exists(fname):
            with open(fname) as f:
                packages_to_migrate_together = yaml_safe_load(f)
        else:
            packages_to_migrate_together = {}

    packages_to_migrate_together_mapping = {}

    for top, pkgs in packages_to_migrate_together.items():
        for pkg in pkgs:
            packages_to_migrate_together_mapping[pkg] = top

    pinning_names = sorted(list(pinnings.keys()))

    feedstocks_to_be_repinned = []
    for pinning_name in pinning_names:
        if (
            pinning_name in packages_to_migrate_together_mapping
            and pinning_name not in packages_to_migrate_together
        ):
            continue
        package_pin_list = pinnings[pinning_name]
        if pin_to_debug is not None and pinning_name != pin_to_debug:
            continue

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

                    # parse back to dict
                    possible_p_dicts = []
                    if isinstance(build.get("run_exports", None), MutableMapping):
                        for _, v in build.get("run_exports", {}).items():
                            for p in v:
                                possible_p_dicts.append(parse_munged_run_export(p))
                    else:
                        for p in build.get("run_exports", []) or []:
                            possible_p_dicts.append(parse_munged_run_export(p))

                    # and check the exported package is within the feedstock
                    exports = [
                        p.get("max_pin", "")
                        for p in possible_p_dicts
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
                    with fold_log_lines(
                        "making pinning migrator for %s" % pinning_name
                    ):
                        pinnings_together = packages_to_migrate_together.get(
                            pinning_name, [pinning_name]
                        )
                        print("    %s:" % pinning_name, flush=True)
                        print("        package name:", package_name, flush=True)
                        print("        feedstock name:", fs_name, flush=True)
                        for p in possible_p_dicts:
                            print("        possible pin spec:", p, flush=True)
                        print(
                            "        migrator:\n"
                            "            curr version: %s\n"
                            "            curr pin: %s\n"
                            "            pin_spec: %s\n"
                            "            pinnings: %s"
                            % (
                                current_version,
                                current_pin,
                                pin_spec,
                                pinnings_together,
                            ),
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
                                pinnings=pinnings_together,
                                full_graph=gx,
                            ),
                        )
            except Exception as e:
                with fold_log_lines(
                    "failed to make pinning migrator for %s" % pinning_name
                ):
                    print("    %s:" % pinning_name, flush=True)
                    print("        package name:", package_name, flush=True)
                    print("        feedstock name:", fs_name, flush=True)
                    print("        error:", repr(e), flush=True)
                continue


def initialize_migrators(
    gx: nx.DiGraph,
    dry_run: bool = False,
) -> MutableSequence[Migrator]:
    migrators: List[Migrator] = []

    add_arch_migrate(migrators, gx)

    add_replacement_migrator(
        migrators,
        gx,
        cast("PackageName", "mpir"),
        cast("PackageName", "gmp"),
        "The package 'mpir' is deprecated and unmaintained. Use 'gmp' instead.",
    )

    pinning_migrators: List[Migrator] = []
    migration_factory(pinning_migrators, gx)
    create_migration_yaml_creator(migrators=pinning_migrators, gx=gx)

    with fold_log_lines("migration graph sizes"):
        print("rebuild migration graph sizes:", flush=True)
        for m in migrators + pinning_migrators:
            if isinstance(m, GraphMigrator):
                print(
                    f'    {getattr(m, "name", m)} graph size: '
                    f'{len(getattr(m, "graph", []))}',
                    flush=True,
                )

    with fold_log_lines("making version migrator"):
        print("building package import maps and version migrator", flush=True)
        python_nodes = {
            n for n, v in gx.nodes("payload") if "python" in v.get("req", "")
        }
        python_nodes.update(
            [
                k
                for node_name, node in gx.nodes("payload")
                for k in node.get("outputs_names", [])
                if node_name in python_nodes
            ],
        )
        version_migrator = Version(
            python_nodes=python_nodes,
            graph=gx,
            pr_limit=PR_LIMIT * 4,
            piggy_back_migrations=[
                CondaForgeYAMLCleanup(),
                Jinja2VarsCleanup(),
                DuplicateLinesCleanup(),
                PipMigrator(),
                LicenseMigrator(),
                CondaForgeYAMLCleanup(),
                ExtraJinja2KeysCleanup(),
                Build2HostMigrator(),
                NoCondaInspectMigrator(),
                PipWheelMigrator(),
                MPIPinRunAsBuildCleanup(),
                DependencyUpdateMigrator(python_nodes),
                StdlibMigrator(),
            ],
        )

        random.shuffle(pinning_migrators)
        migrators = [version_migrator] + migrators + pinning_migrators

    return migrators


def _load(name):
    with LazyJson(f"migrators/{name}.json") as lzj:
        return make_from_lazy_json_data(lzj.data)


def load_migrators(skip_paused: bool = True) -> MutableSequence[Migrator]:
    """Loads all current migrators.

    Parameters
    ----------
    skip_paused : bool, optional
        Whether to skip paused migrators, defaults to True.

    Returns
    -------
    migrators : list of Migrator
        The list of migrators to run in the correct randomized order.
    """
    migrators = []
    version_migrator = None
    pinning_migrators = []
    longterm_migrators = []
    all_names = get_all_keys_for_hashmap("migrators")
    with executor("process", 4) as pool:
        futs = [pool.submit(_load, name) for name in all_names]

        for fut in tqdm.tqdm(
            as_completed(futs), desc="loading migrators", ncols=80, total=len(all_names)
        ):
            migrator = fut.result()

            if getattr(migrator, "paused", False) and skip_paused:
                continue

            if isinstance(migrator, Version):
                version_migrator = migrator
            elif isinstance(migrator, MigrationYamlCreator) or isinstance(
                migrator, MigrationYaml
            ):
                if getattr(migrator, "longterm", False):
                    longterm_migrators.append(migrator)
                else:
                    pinning_migrators.append(migrator)
            else:
                migrators.append(migrator)

    if version_migrator is None:
        raise RuntimeError("No version migrator found in the migrators directory!")

    random.shuffle(pinning_migrators)
    random.shuffle(longterm_migrators)
    migrators = [version_migrator] + migrators + pinning_migrators + longterm_migrators

    return migrators


def main(ctx: CliContext) -> None:
    gx = load_existing_graph()
    migrators = initialize_migrators(
        gx,
        dry_run=ctx.dry_run,
    )
    with (
        fold_log_lines("dumping migrators to JSON"),
        lazy_json_override_backends(
            ["file"],
            hashmaps_to_sync=["migrators"],
        ),
    ):
        old_migrators = set(get_all_keys_for_hashmap("migrators"))
        new_migrators = set()
        for migrator in tqdm.tqdm(
            migrators, desc="dumping migrators", ncols=80, total=len(migrators)
        ):
            try:
                data = migrator.to_lazy_json_data()
                if data["name"] in new_migrators:
                    raise RuntimeError(f"Duplicate migrator name: {data['name']}!")

                new_migrators.add(data["name"])

                with LazyJson(f"migrators/{data['name']}.json") as lzj:
                    lzj.update(data)

            except Exception as e:
                logger.error(f"Error dumping migrator {migrator} to JSON!", exc_info=e)

        migrators_to_remove = old_migrators - new_migrators
        for migrator in migrators_to_remove:
            remove_key_for_hashmap("migrators", migrator)
