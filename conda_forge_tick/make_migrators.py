import contextlib
import copy
import glob
import logging
import os
import pprint
import re
import secrets
import sys
import time
from concurrent.futures import as_completed
from typing import (
    Any,
    List,
    Mapping,
    MutableMapping,
    MutableSequence,
    Never,
    cast,
)

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
    AddNVIDIATools,
    ArchRebuild,
    CombineV1ConditionsMigrator,
    CondaForgeYAMLCleanup,
    CrossCompilationForARMAndPower,
    CrossPythonMigrator,
    CrossRBaseMigrator,
    CrossRBaseWinMigrator,
    DependencyUpdateMigrator,
    DuplicateLinesCleanup,
    ExtraJinja2KeysCleanup,
    FlangMigrator,
    GuardTestingMigrator,
    GuardTestingWinMigrator,
    Jinja2VarsCleanup,
    LibboostMigrator,
    LicenseMigrator,
    MigrationYaml,
    Migrator,
    MiniMigrator,
    MiniReplacement,
    MPIPinRunAsBuildCleanup,
    NoarchPythonMinMigrator,
    NoCondaInspectMigrator,
    Numpy2Migrator,
    PipMigrator,
    PipWheelMigrator,
    PyPIOrgMigrator,
    Replacement,
    RUCRTCleanup,
    StaticLibMigrator,
    StdlibMigrator,
    UpdateCMakeArgsMigrator,
    UpdateCMakeArgsWinMigrator,
    UpdateConfigSubGuessMigrator,
    Version,
    YAMLRoundTrip,
    make_from_lazy_json_data,
)
from conda_forge_tick.migrators.arch import OSXArm, WinArm64
from conda_forge_tick.migrators.migration_yaml import MigrationYamlCreator
from conda_forge_tick.migrators_types import BuildRunExportsDict, PackageName
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import (
    CB_CONFIG,
    fold_log_lines,
    get_recipe_schema_version,
    load_existing_graph,
    parse_meta_yaml,
    parse_munged_run_export,
    parse_recipe_yaml,
    pluck,
    yaml_safe_load,
)

logger = logging.getLogger(__name__)

RNG = secrets.SystemRandom()

PR_LIMIT = 5
PR_ATTEMPT_LIMIT_FACTOR = 2
MAX_PR_LIMIT = 20
FORCE_PR_AFTER_SOLVER_ATTEMPTS = 10
CHECK_SOLVABLE_TIMEOUT = 30  # in days
DEFAULT_MINI_MIGRATORS = [
    CondaForgeYAMLCleanup,
    Jinja2VarsCleanup,
    DuplicateLinesCleanup,
    PipMigrator,
    LicenseMigrator,
    CondaForgeYAMLCleanup,
    ExtraJinja2KeysCleanup,
    NoCondaInspectMigrator,
    MPIPinRunAsBuildCleanup,
    PyPIOrgMigrator,
    CombineV1ConditionsMigrator,
]


def _make_mini_migrators_with_defaults(
    extra_mini_migrators: list[MiniMigrator] | None = None,
) -> list[MiniMigrator]:
    extra_mini_migrators = extra_mini_migrators or []
    for klass in DEFAULT_MINI_MIGRATORS:
        if not any(isinstance(m, klass) for m in extra_mini_migrators):
            extra_mini_migrators.append(klass())
    return extra_mini_migrators


def _compute_migrator_pr_limit(
    migrator: Migrator, nominal_pr_limit: int
) -> tuple[int, int, float]:
    # adaptively set PR limits based on the number of PRs made so far
    if migrator.graph is None:
        raise ValueError("graph is None")
    number_pred = 0
    for _, v in migrator.graph.nodes.items():
        payload = v.get("payload", {}) or {}
        if not isinstance(payload, LazyJson):
            payload = contextlib.nullcontext(enter_result=payload)

        with payload as p:
            muid = migrator.migrator_uid(p)  # type: ignore[arg-type]
            pr_info = p.get("pr_info", {}) or {}
            if not isinstance(pr_info, LazyJson):
                pr_info = contextlib.nullcontext(enter_result=pr_info)
            with pr_info as pri:
                muids = [
                    pred.get("data", {}) or {} for pred in (pri.get("PRed", []) or [])
                ]
                if muid in muids:
                    number_pred += 1

    tot_nodes = len(migrator.graph.nodes)
    frac_pred = number_pred / tot_nodes if tot_nodes > 0 else 1.0

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
        min(int(nominal_pr_limit * 2), MAX_PR_LIMIT),
        min(int(nominal_pr_limit * 1.75), MAX_PR_LIMIT),
        min(int(nominal_pr_limit * 1.50), MAX_PR_LIMIT),
        min(int(nominal_pr_limit * 1.25), MAX_PR_LIMIT),
        min(nominal_pr_limit, MAX_PR_LIMIT),
    ]

    pr_limit = None
    for i, lim in enumerate(number_pred_breaks):
        if number_pred <= lim:
            pr_limit = pr_limits[i]
            break

    if pr_limit is None:
        pr_limit = nominal_pr_limit

    return pr_limit, number_pred, frac_pred


def add_replacement_migrator(
    migrators: MutableSequence[Migrator],
    gx: nx.DiGraph,
    old_pkg: "PackageName",
    new_pkg: "PackageName",
    rationale: str,
    alt_migrator: type[Replacement] | None = None,
) -> None:
    """Add a migrator to replace one package with another.

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
        if alt_migrator is not None:
            migrators.append(
                alt_migrator(
                    old_pkg=old_pkg,
                    new_pkg=new_pkg,
                    rationale=rationale,
                    pr_limit=PR_LIMIT,
                    total_graph=gx,
                ),
            )
        else:
            migrators.append(
                Replacement(
                    old_pkg=old_pkg,
                    new_pkg=new_pkg,
                    rationale=rationale,
                    pr_limit=PR_LIMIT,
                    total_graph=gx,
                ),
            )

        # adaptively set PR limits based on the number of PRs made so far
        pr_limit, _, _ = _compute_migrator_pr_limit(
            migrators[-1],
            PR_LIMIT,
        )
        migrators[-1].pr_limit = pr_limit


def add_arch_migrate(migrators: MutableSequence[Migrator], gx: nx.DiGraph) -> None:
    """Add rebuild migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """
    with fold_log_lines("making aarch64+ppc64le migrator"):
        migrators.append(
            ArchRebuild(
                total_graph=gx,
                pr_limit=PR_LIMIT,
            ),
        )

    with fold_log_lines("making osx-arm64 migrator"):
        migrators.append(
            OSXArm(
                total_graph=gx,
                pr_limit=PR_LIMIT,
                piggy_back_migrations=[
                    UpdateConfigSubGuessMigrator(),
                    CondaForgeYAMLCleanup(),
                    UpdateCMakeArgsMigrator(),
                    GuardTestingMigrator(),
                    CrossRBaseMigrator(),
                    CrossPythonMigrator(),
                    NoCondaInspectMigrator(),
                    MPIPinRunAsBuildCleanup(),
                    CombineV1ConditionsMigrator(),
                ],
            ),
        )

    with fold_log_lines("making win-arm64 migrator"):
        migrators.append(
            WinArm64(
                total_graph=gx,
                pr_limit=PR_LIMIT,
                piggy_back_migrations=[
                    CondaForgeYAMLCleanup(),
                    UpdateCMakeArgsWinMigrator(),
                    GuardTestingWinMigrator(),
                    CrossRBaseWinMigrator(),
                    CrossPythonMigrator(),
                    NoCondaInspectMigrator(),
                    MPIPinRunAsBuildCleanup(),
                    CombineV1ConditionsMigrator(),
                ],
            ),
        )


def add_rebuild_migration_yaml(
    migrators: MutableSequence[Migrator],
    gx: nx.DiGraph,
    migration_yaml: str,
    config: dict,
    migration_name: str,
    nominal_pr_limit: int = PR_LIMIT,
    force_pr_after_solver_attempts: int = FORCE_PR_AFTER_SOLVER_ATTEMPTS,
    paused: bool = False,
) -> None:
    """Add rebuild migrator.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.
    gx : networkx.DiGraph
        The feedstock graph
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
    piggy_back_migrations = [
        CrossCompilationForARMAndPower(),
        StdlibMigrator(),
    ]
    if migration_name == "qt515":
        piggy_back_migrations.append(
            MiniReplacement(old_pkg=PackageName("qt"), new_pkg=PackageName("qt-main"))
        )
    if migration_name == "jpeg_to_libjpeg_turbo":
        piggy_back_migrations.append(
            MiniReplacement(
                old_pkg=PackageName("jpeg"), new_pkg=PackageName("libjpeg-turbo")
            )
        )
    if migration_name == "libxml2214":
        piggy_back_migrations.append(
            MiniReplacement(
                old_pkg=PackageName("libxml2"), new_pkg=PackageName("libxml2-devel")
            )
        )
    if migration_name == "boost_cpp_to_libboost":
        piggy_back_migrations.append(LibboostMigrator())
    if migration_name == "numpy2":
        piggy_back_migrations.append(Numpy2Migrator())
    if migration_name.startswith("r-base44"):
        piggy_back_migrations.append(RUCRTCleanup())
    if migration_name.startswith("flang19") or migration_name.startswith("flang21"):
        piggy_back_migrations.append(FlangMigrator())
    if migration_name.startswith("xz_to_liblzma_devel"):
        piggy_back_migrations.append(
            MiniReplacement(
                old_pkg=PackageName("xz"), new_pkg=PackageName("liblzma-devel")
            )
        )
    piggy_back_migrations = _make_mini_migrators_with_defaults(
        extra_mini_migrators=piggy_back_migrations
    )

    migrator = MigrationYaml(
        migration_yaml,
        name=migration_name,
        total_graph=gx,
        pr_limit=nominal_pr_limit,
        piggy_back_migrations=piggy_back_migrations,
        force_pr_after_solver_attempts=force_pr_after_solver_attempts,
        paused=paused,
        **config,
    )

    # adaptively set PR limits based on the number of PRs made so far
    pr_limit, number_pred, frac_pred = _compute_migrator_pr_limit(
        migrator,
        nominal_pr_limit,
    )
    migrator.pr_limit = pr_limit

    print(f"migration yaml:\n{migration_yaml.rstrip()}", flush=True)
    print(f"bump number: {migrator.bump_number}", flush=True)
    print(
        f"# of PRs made so far: {number_pred} ({frac_pred * 100:0.2f} percent)",
        flush=True,
    )
    final_config = {}
    final_config.update(config)
    final_config["pr_limit"] = migrator.pr_limit
    print("final config:\n", pprint.pformat(final_config), flush=True)
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

    for yaml_file, yaml_contents in migration_yamls:
        loaded_yaml = yaml_safe_load(yaml_contents)
        __mname = os.path.splitext(os.path.basename(yaml_file))[0]

        if __mname not in only_keep:
            continue

        with fold_log_lines(f"making {__mname} migrator"):
            migrator_config = loaded_yaml.get("__migrator", {})
            paused = migrator_config.pop("paused", False)
            _pr_limit = min(migrator_config.pop("pr_limit", pr_limit), MAX_PR_LIMIT)
            force_pr_after_solver_attempts = min(
                migrator_config.pop(
                    "force_pr_after_solver_attempts",
                    FORCE_PR_AFTER_SOLVER_ATTEMPTS,
                ),
                FORCE_PR_AFTER_SOLVER_ATTEMPTS,
            )
            # max_solver_attempts was removed from the migrator classes
            # so we remove it from the config here too
            if "max_solver_attempts" in migrator_config:
                del migrator_config["max_solver_attempts"]

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
                migration_yaml=yaml_contents,
                migration_name=os.path.splitext(yaml_file)[0],
                config=migrator_config,
                nominal_pr_limit=_pr_limit,
                force_pr_after_solver_attempts=force_pr_after_solver_attempts,
                paused=paused,
            )
            if skip_solver_checks:
                assert not migrators[-1].check_solvable

            if paused:
                print(f"skipping migration {__mname} because it is paused", flush=True)

            print("\n", flush=True)
            sys.stdout.flush()
            sys.stderr.flush()


def _get_max_pin_from_pinning_dict(
    pinning_dict: Mapping[str, Any], recipe_version: int
):
    """Given a pinning dictionary in the format returned by parse_munged_run_export,
    return the value for max_pin.

    In recipe v0, this is the value of the key "max_pin".
    In recipe v1, this is the value of the key "upper_bound", but only if it has the
    format of a pinning spec and is not a hard-coded version string.

    Returns
    -------
    str
        The value for max_pin, or an empty string if not defined or not a pinning spec.

    Raises
    ------
    ValueError
        If the schema version of the recipe is neither 0 nor 1.
    """
    pinning_spec_regex = re.compile(r"^(x\.)*x$")

    if recipe_version == 0:
        value = pinning_dict.get("max_pin", "")
    elif recipe_version == 1:
        value = pinning_dict.get("upper_bound", "")
    else:
        raise ValueError(f"Unsupported schema version: {recipe_version}")

    if pinning_spec_regex.match(value):
        return value
    return ""


def _extract_most_stringent_pin_from_recipe(
    feedstock_name: str,
    package_name: str,
    feedstock_attrs: Mapping[str, Any],
    gx: nx.DiGraph,
) -> tuple[str, list[dict]]:
    """Given the name of a package that is specified in the run_exports in a feedstock,
    find the run_exports pinning specification that is most stringent for that package
    in the feedstock recipe.
    We do that by considering all run_exports sections from outputs of the feedstock.
    The package must also be an output of the feedstock.

    Parameters
    ----------
    feedstock_name
        Name of the feedstock to analyze.
    package_name
        Name of the package that is specified as run_exports.
    feedstock_attrs
        Node attributes of the feedstock.
    gx
        Instance of the global cf-graph.

    Returns
    -------
    tuple[str, list[dict]]
        A tuple containing:
        - The most stringent pinning spec found. If the package is not found in the recipe,
          this will be an empty string.
        - A list of all run_exports dictionaries found in the recipe, in the format
          returned by parse_munged_run_export.

    Raises
    ------
    ValueError
        If the schema version of the recipe is neither 0 nor 1.
    """
    schema_version = get_recipe_schema_version(feedstock_attrs)
    # we need a special parsing for pinning stuff
    if schema_version == 0:
        meta_yaml = parse_meta_yaml(
            feedstock_attrs["raw_meta_yaml"],
            for_pinning=True,
        )
    elif schema_version == 1:
        meta_yaml = parse_recipe_yaml(
            feedstock_attrs["raw_meta_yaml"],
            for_pinning=True,
        )
    else:
        raise ValueError(f"Unsupported schema version: {schema_version}")
    # find the most stringent max pin for this feedstock if any
    pin_spec = ""
    possible_p_dicts = []
    for block in [meta_yaml] + meta_yaml.get("outputs", []) or []:
        build = block.get("build", {}) or {}

        # parse back to dict
        if isinstance(build.get("run_exports", None), MutableMapping):
            run_exports: (
                list[PackageName] | BuildRunExportsDict | dict[Never, Never]
            ) = build.get("run_exports", {})
            if run_exports is None:
                raise ValueError("run_exports is None")
            if isinstance(run_exports, list):
                raise ValueError("run_exports is a list")
            for _, v in run_exports.items():
                for p in v:  # type: ignore[attr-defined]
                    possible_p_dicts.append(parse_munged_run_export(p))
        else:
            for p in build.get("run_exports", []) or []:
                possible_p_dicts.append(parse_munged_run_export(p))

        # and check the exported package is within the feedstock
        exports = [
            _get_max_pin_from_pinning_dict(p, schema_version)
            for p in possible_p_dicts
            # make certain not direct hard pin
            if isinstance(p, MutableMapping)
            # ensure the export is for this package
            and p.get("package_name", "") == package_name
            # ensure the pinned package is in an output of the
            # parent feedstock
            and (
                feedstock_name
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
    return pin_spec, possible_p_dicts


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


def _compute_approximate_pinning_migration_sizes(
    gx,
    pinning_names,
    packages_to_migrate_together_mapping,
    packages_to_migrate_together,
    pinnings,
):
    pinning_migration_sizes = {pinning_name: 0 for pinning_name in pinning_names}
    for node in list(gx.nodes):
        with gx.nodes[node]["payload"] as attrs:
            for pinning_name in pinning_names:
                if (
                    pinning_name in packages_to_migrate_together_mapping
                    and pinning_name not in packages_to_migrate_together
                ):
                    continue

                if pinning_name not in gx.graph["outputs_lut"]:
                    # conda_build_config.yaml can't have `-` unlike our package names
                    package_name = pinning_name.replace("_", "-")
                else:
                    package_name = pinning_name

                requirements = attrs.get("requirements", {})
                host = requirements.get("host", set())
                build = requirements.get("build", set())
                bh = host or build
                if package_name in bh:
                    pinning_migration_sizes[pinning_name] += 1

    return pinning_migration_sizes


def create_migration_yaml_creator(
    migrators: MutableSequence[Migrator], gx: nx.DiGraph, pin_to_debug=None
):
    cfp_gx = copy.deepcopy(gx)
    for node in list(cfp_gx.nodes):
        if node != "conda-forge-pinning":
            pluck(cfp_gx, node)
    cfp_gx.remove_edges_from(nx.selfloop_edges(cfp_gx))

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

    pinning_migration_sizes = _compute_approximate_pinning_migration_sizes(
        gx,
        pinning_names,
        packages_to_migrate_together_mapping,
        packages_to_migrate_together,
        pinnings,
    )

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
        feedstock_name = next(
            iter(
                sorted(gx.graph["outputs_lut"].get(package_name, {package_name})),
            ),
        )

        if feedstock_name not in gx.nodes:
            continue
        feedstock_attrs = gx.nodes[feedstock_name]["payload"]

        if (
            feedstock_attrs.get("archived", False)
            or not feedstock_attrs.get("version")
            or feedstock_name in feedstocks_to_be_repinned
        ):
            continue

        current_pins = list(map(str, package_pin_list))
        current_version = str(feedstock_attrs["version"])

        try:
            pin_spec, possible_p_dicts = _extract_most_stringent_pin_from_recipe(
                feedstock_name, package_name, feedstock_attrs, gx
            )

            # fall back to the pinning file or "x"
            if not pin_spec:
                # since this comes from conda_build_config.yaml, max_pin is correct for v1 as well
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
                feedstocks_to_be_repinned.append(feedstock_name)
                with fold_log_lines("making pinning migrator for %s" % pinning_name):
                    pinnings_together = packages_to_migrate_together.get(
                        pinning_name, [pinning_name]
                    )
                    print("%s:" % pinning_name, flush=True)
                    print("    package name:", package_name, flush=True)
                    print("    feedstock name:", feedstock_name, flush=True)
                    for p in possible_p_dicts:
                        print("    possible pin spec:", p, flush=True)
                    print(
                        "    migrator:\n"
                        "        curr version: %s\n"
                        "        curr pin: %s\n"
                        "        pin_spec: %s\n"
                        "        pinnings: %s"
                        % (
                            current_version,
                            current_pin,
                            pin_spec,
                            pinnings_together,
                        ),
                        flush=True,
                    )
                    print(" ", flush=True)
                    migrators.append(
                        MigrationYamlCreator(
                            package_name=pinning_name,
                            new_pin_version=current_version,
                            current_pin=current_pin,
                            pin_spec=pin_spec,
                            feedstock_name=feedstock_name,
                            total_graph=cfp_gx,
                            pinnings=pinnings_together,
                            pr_limit=1,
                            pin_impact=pinning_migration_sizes[pinning_name],
                        ),
                    )
        except Exception as e:
            with fold_log_lines(
                "failed to make pinning migrator for %s" % pinning_name
            ):
                print("%s:" % pinning_name, flush=True)
                print("    package name:", package_name, flush=True)
                print("    feedstock name:", feedstock_name, flush=True)
                print("    error:", repr(e), flush=True)
                print(" ", flush=True)
            continue


def add_noarch_python_min_migrator(
    migrators: MutableSequence[Migrator], gx: nx.DiGraph
):
    with fold_log_lines("making `noarch: python` migrator"):
        migrators.append(
            NoarchPythonMinMigrator(
                total_graph=gx,
                pr_limit=PR_LIMIT,
                piggy_back_migrations=_make_mini_migrators_with_defaults(
                    extra_mini_migrators=[YAMLRoundTrip()],
                ),
            ),
        )

        # adaptively set PR limits based on the number of PRs made so far
        pr_limit, _, _ = _compute_migrator_pr_limit(
            migrators[-1],
            PR_LIMIT,
        )
        migrators[-1].pr_limit = pr_limit


def add_static_lib_migrator(migrators: MutableSequence[Migrator], gx: nx.DiGraph):
    with fold_log_lines("making static lib migrator"):
        migrators.append(
            StaticLibMigrator(
                total_graph=gx,
                pr_limit=PR_LIMIT,
                piggy_back_migrations=_make_mini_migrators_with_defaults(
                    extra_mini_migrators=[YAMLRoundTrip()],
                ),
            ),
        )

        # adaptively set PR limits based on the number of PRs made so far
        pr_limit, _, _ = _compute_migrator_pr_limit(
            migrators[-1],
            PR_LIMIT,
        )
        migrators[-1].pr_limit = pr_limit


def add_nvtools_migrator(
    migrators: MutableSequence[Migrator],
    gx: nx.DiGraph,
):
    with fold_log_lines("making add nvtools migrator"):
        migrators.append(
            AddNVIDIATools(
                check_solvable=False,
                total_graph=gx,
                pr_limit=PR_LIMIT,
                piggy_back_migrations=_make_mini_migrators_with_defaults(
                    extra_mini_migrators=[YAMLRoundTrip()],
                ),
            )
        )
        pr_limit, _, _ = _compute_migrator_pr_limit(
            migrators[-1],
            PR_LIMIT,
        )
        migrators[-1].pr_limit = pr_limit


def _make_version_migrator(
    gx: nx.DiGraph,
    dry_run: bool = False,
) -> Version:
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
            total_graph=gx,
            pr_limit=PR_LIMIT * 2,
            piggy_back_migrations=_make_mini_migrators_with_defaults(
                extra_mini_migrators=[
                    PipWheelMigrator(),
                    DependencyUpdateMigrator(python_nodes),
                    StdlibMigrator(),
                ],
            ),
        )

    return version_migrator


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

    add_replacement_migrator(
        migrators,
        gx,
        cast("PackageName", "astropy"),
        cast("PackageName", "astropy-base"),
        "The astropy feedstock has been split into two packages, astropy-base only "
        "has required dependencies and astropy now has all optional dependencies. "
        "To maintain the old behavior you should migrate to astropy-base.",
    )

    add_noarch_python_min_migrator(migrators, gx)

    add_static_lib_migrator(migrators, gx)

    add_nvtools_migrator(migrators, gx)

    pinning_migrators: List[Migrator] = []
    migration_factory(pinning_migrators, gx)
    create_migration_yaml_creator(migrators=pinning_migrators, gx=gx)

    version_migrator = _make_version_migrator(gx, dry_run=dry_run)

    RNG.shuffle(pinning_migrators)
    migrators = [version_migrator] + migrators + pinning_migrators

    with fold_log_lines("migration graph sizes"):
        print("rebuild migration graph sizes:", flush=True)
        for m in migrators:
            print(
                f"    {getattr(m, 'name', m)} graph size: "
                f"{len(getattr(m, 'graph', []))}",
                flush=True,
            )

    return migrators


def _load(name):
    with LazyJson(f"migrators/{name}.json") as lzj:
        return make_from_lazy_json_data(lzj.data)


def load_migrators(skip_paused: bool = True) -> MutableSequence[Migrator]:
    """Load all current migrators.

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
    pinning_migrators = []
    longterm_migrators = []
    all_names = get_all_keys_for_hashmap("migrators")
    # Only load python314 and python314t migrators - filter BEFORE submitting to pool
    allowed_migrators = {"python314", "python314t"}
    all_names = [name for name in all_names if name in allowed_migrators]
    print(f"Loading only: {all_names}", flush=True)

    with executor("process", 2) as pool:
        futs = [pool.submit(_load, name) for name in all_names]

        for fut in tqdm.tqdm(
            as_completed(futs), desc="loading migrators", ncols=80, total=len(all_names)
        ):
            migrator = fut.result()

            if getattr(migrator, "paused", False) and skip_paused:
                continue

            if isinstance(migrator, Version):
                pass
            elif isinstance(migrator, MigrationYamlCreator) or isinstance(
                migrator, MigrationYaml
            ):
                if getattr(migrator, "longterm", False):
                    longterm_migrators.append(migrator)
                else:
                    pinning_migrators.append(migrator)
            else:
                migrators.append(migrator)

    # Commented out - version migrator is slow
    # version_migrator = _make_version_migrator(load_existing_graph())

    RNG.shuffle(pinning_migrators)
    RNG.shuffle(longterm_migrators)
    # migrators = [version_migrator] + migrators + pinning_migrators + longterm_migrators
    migrators = migrators + pinning_migrators + longterm_migrators

    return migrators


def dump_migrators(migrators: MutableSequence[Migrator], dry_run: bool = False) -> None:
    """Dump the current migrators to JSON.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to dump.
    dry_run : bool, optional
        Whether to perform a dry run, defaults to False. If True, no changes will be made.

    Raises
    ------
    RuntimeError
        If a duplicate migrator name is found.
    """
    if dry_run:
        print("dry run: dumping migrators to json", flush=True)
        return

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
            # skip dumping the version migrator since we remake it on the fly
            if isinstance(migrator, Version):
                continue

            try:
                data = migrator.to_lazy_json_data()
                if data["name"] in new_migrators:
                    raise RuntimeError(f"Duplicate migrator name: {data['name']}!")

                new_migrators.add(data["name"])

                with LazyJson(f"migrators/{data['name']}.json") as lzj:
                    lzj.update(data)

            except Exception as e:
                logger.error("Error dumping migrator %s to JSON!", migrator, exc_info=e)

        migrators_to_remove = old_migrators - new_migrators
        for migrator in migrators_to_remove:
            remove_key_for_hashmap("migrators", migrator)


def main(ctx: CliContext) -> None:
    gx = load_existing_graph()
    migrators = initialize_migrators(
        gx,
        dry_run=ctx.dry_run,
    )
    dump_migrators(
        migrators,
        dry_run=ctx.dry_run,
    )
