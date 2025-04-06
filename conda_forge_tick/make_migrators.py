import contextlib
import glob
import logging
import os
import pprint
import re
import secrets
import time
import typing
from concurrent.futures import as_completed
from typing import (
    Any,
    Mapping,
    MutableMapping,
    MutableSequence,
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
    AddNVIDIATools,
    ArchRebuild,
    CombineV1ConditionsMigrator,
    CondaForgeYAMLCleanup,
    CrossCompilationForARMAndPower,
    CrossPythonMigrator,
    CrossRBaseMigrator,
    DependencyUpdateMigrator,
    DuplicateLinesCleanup,
    ExtraJinja2KeysCleanup,
    FlangMigrator,
    GuardTestingMigrator,
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
    UpdateConfigSubGuessMigrator,
    Version,
    YAMLRoundTrip,
    make_from_lazy_json_data,
)
from conda_forge_tick.migrators.arch import OSXArm
from conda_forge_tick.migrators.migration_yaml import MigrationYamlCreator
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import (
    CB_CONFIG,
    fold_log_lines,
    get_recipe_schema_version,
    load_existing_graph,
    parse_meta_yaml,
    parse_munged_run_export,
    parse_recipe_yaml,
    yaml_safe_load,
)

logger = logging.getLogger(__name__)

RNG = secrets.SystemRandom()

PR_LIMIT = 5
PR_ATTEMPT_LIMIT_FACTOR = 2
MAX_PR_LIMIT = 20
MAX_SOLVER_ATTEMPTS = 3
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

HEADER = """\
\n>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
>"""


def _make_mini_migrators_with_defaults(
    extra_mini_migrators: list[MiniMigrator] = None,
) -> list[MiniMigrator]:
    extra_mini_migrators = extra_mini_migrators or []
    for klass in DEFAULT_MINI_MIGRATORS:
        if not any(isinstance(m, klass) for m in extra_mini_migrators):
            extra_mini_migrators.append(klass())
    return extra_mini_migrators


def _compute_migrator_pr_limit(
    migrator: Migrator, nominal_pr_limit: int
) -> (int, int, float):
    # adaptively set PR limits based on the number of PRs made so far
    number_pred = 0
    for _, v in migrator.graph.nodes.items():
        payload = v.get("payload", {}) or {}
        if not isinstance(payload, LazyJson):
            payload = contextlib.nullcontext(enter_result=payload)

        with payload as p:
            muid = migrator.migrator_uid(p)
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


def make_replacement_migrator(
    old_pkg: "PackageName",
    new_pkg: "PackageName",
    rationale: str,
    alt_migrator: Union[Migrator, None] = None,
) -> None:
    """Adds a migrator to replace one package with another.

    Parameters
    ----------
    old_pkg : str
        The package to be replaced.
    new_pkg : str
        The package to replace the `old_pkg`.
    rationale : str
        The reason the for the migration. Should be a full statement.
    alt_migrator : Replacement migrator or a subclass thereof
        An alternate Replacement migrator to use for special tasks.

    Returns
    -------
    migrators : list of Migrator
        The list of migrators to run.
    """
    gx = load_existing_graph()

    migrators = []

    tqdm.tqdm.write(f"{HEADER} making replacement migrator for {old_pkg} -> {new_pkg}")

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

    return migrators


def make_arch_migrators() -> None:
    """Makes arch rebuild migrators.

    Returns
    -------
    migrators : list of Migrator
        The list of migrators to run.
    """
    migrators = []

    tqdm.tqdm.write(f"{HEADER} making aarch64+ppc64le migrator")
    migrators.append(
        ArchRebuild(
            total_graph=load_existing_graph(),
            pr_limit=PR_LIMIT,
        ),
    )

    tqdm.tqdm.write(f"{HEADER} making osx-arm64 migrator")
    migrators.append(
        OSXArm(
            total_graph=load_existing_graph(),
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

    return migrators


def make_rebuild_migration_yaml(
    yaml_file: str,
    migration_yaml: str,
) -> None:
    """Makes a rebuild migrator.

    Parameters
    ----------
    yaml_file : str
        The name of the yaml file
    migration_yaml : str
        The raw yaml for the migration variant dict

    Returns
    -------
    migrators : list of Migrator
        The list of migrators to run.
    """
    migrators = []
    messages = []

    migration_name = os.path.splitext(os.path.basename(yaml_file))[0]
    loaded_yaml = yaml_safe_load(migration_yaml)

    migrator_config = loaded_yaml.get("__migrator", {})
    paused = migrator_config.pop("paused", False)
    nominal_pr_limit = min(migrator_config.pop("pr_limit", PR_LIMIT), MAX_PR_LIMIT)
    max_solver_attempts = min(
        migrator_config.pop("max_solver_attempts", MAX_SOLVER_ATTEMPTS),
        MAX_SOLVER_ATTEMPTS,
    )
    force_pr_after_solver_attempts = min(
        migrator_config.pop(
            "force_pr_after_solver_attempts",
            FORCE_PR_AFTER_SOLVER_ATTEMPTS,
        ),
        FORCE_PR_AFTER_SOLVER_ATTEMPTS,
    )

    messages.append(f"making {migration_name} migrator")
    age = time.time() - loaded_yaml.get("migrator_ts", time.time())
    age /= 24 * 60 * 60
    messages.append("migrator %s is %d days old" % (migration_name, int(age)))
    if (
        age > CHECK_SOLVABLE_TIMEOUT
        and "check_solvable" not in migrator_config
        and not migrator_config.get("longterm", False)
    ):
        migrator_config["check_solvable"] = False
        messages.append(
            "turning off solver checks for migrator "
            "%s since over %d is over limit %d"
            % (
                migration_name,
                age,
                CHECK_SOLVABLE_TIMEOUT,
            )
        )
        skip_solver_checks = True
    else:
        skip_solver_checks = False

    piggy_back_migrations = [
        CrossCompilationForARMAndPower(),
        StdlibMigrator(),
    ]
    if migration_name == "qt515":
        piggy_back_migrations.append(MiniReplacement(old_pkg="qt", new_pkg="qt-main"))
    if migration_name == "jpeg_to_libjpeg_turbo":
        piggy_back_migrations.append(
            MiniReplacement(old_pkg="jpeg", new_pkg="libjpeg-turbo")
        )
    if migration_name == "boost_cpp_to_libboost":
        piggy_back_migrations.append(LibboostMigrator())
    if migration_name == "numpy2":
        piggy_back_migrations.append(Numpy2Migrator())
    if migration_name.startswith("r-base44"):
        piggy_back_migrations.append(RUCRTCleanup())
    if migration_name.startswith("flang19"):
        piggy_back_migrations.append(FlangMigrator())
    if migration_name.startswith("xz_to_liblzma_devel"):
        piggy_back_migrations.append(
            MiniReplacement(old_pkg="xz", new_pkg="liblzma-devel")
        )
    piggy_back_migrations = _make_mini_migrators_with_defaults(
        extra_mini_migrators=piggy_back_migrations
    )

    migrator = MigrationYaml(
        migration_yaml,
        name=migration_name,
        total_graph=load_existing_graph(),
        pr_limit=nominal_pr_limit,
        piggy_back_migrations=piggy_back_migrations,
        max_solver_attempts=max_solver_attempts,
        force_pr_after_solver_attempts=force_pr_after_solver_attempts,
        paused=paused,
        **migrator_config,
    )

    # adaptively set PR limits based on the number of PRs made so far
    pr_limit, number_pred, frac_pred = _compute_migrator_pr_limit(
        migrator,
        nominal_pr_limit,
    )
    migrator.pr_limit = pr_limit

    messages.append(f"migration yaml:\n{migration_yaml.strip()}")
    messages.append(f"bump number: {migrator.bump_number}")
    messages.append(
        f"# of PRs made so far: {number_pred} ({frac_pred * 100:0.2f} percent)"
    )
    final_config = {}
    final_config.update(migrator_config)
    final_config["pr_limit"] = migrator.pr_limit
    final_config["max_solver_attempts"] = max_solver_attempts
    messages.append("final config:")
    messages.append(pprint.pformat(final_config))
    migrators.append(migrator)

    if skip_solver_checks:
        assert not migrators[-1].check_solvable

    if paused:
        messages.append(f"skipping migration {migration_name} because it is paused")

    tqdm.tqdm.write(f"{HEADER} " + "\n".join(messages) + "\n")

    return migrators


def migration_factory(
    only_keep=None,
    pool=None,
):
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

    migrators_or_futs = []
    for yaml_file, yaml_contents in migration_yamls:
        __mname = os.path.splitext(os.path.basename(yaml_file))[0]

        if __mname not in only_keep:
            continue

        if pool is None:
            migrators_or_futs.extend(
                make_rebuild_migration_yaml(yaml_file, yaml_contents)
            )
        else:
            migrators_or_futs.append(
                pool.submit(make_rebuild_migration_yaml, yaml_file, yaml_contents)
            )

    return migrators_or_futs


def _get_max_pin_from_pinning_dict(
    pinning_dict: Mapping[str, Any], recipe_version: int
):
    """
    Given a pinning dictionary in the format returned by parse_munged_run_export,
    return the value for max_pin.

    In recipe v0, this is the value of the key "max_pin".
    In recipe v1, this is the value of the key "upper_bound", but only if it has the
    format of a pinning spec and is not a hard-coded version string.

    :return: the value for max_pin, or an empty string if not defined or not a pinning spec.
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
    """
    Given the name of a package that is specified in the run_exports in a feedstock,
    find the run_exports pinning specification that is most stringent for that package
    in the feedstock recipe.
    We do that by considering all run_exports sections from outputs of the feedstock.
    The package must also be an output of the feedstock.

    :param feedstock_name: name of the feedstock to analyze
    :param package_name: name of the package that is specified as run_exports
    :param feedstock_attrs: the node attributes of the feedstock
    :param gx: an instance of the global cf-graph

    :return: a tuple (pin_spec, possible_p_dicts) where pin_spec is the most stringent
    pinning spec found and possible_p_dicts is a list of all the run_exports dictionaries
    that were found in the recipe, in the format returned by parse_munged_run_export.
    If the package is not found in the recipe, pin_spec is an empty string and
    possible_p_dicts still contains all the run_exports dictionaries.
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
            for _, v in build.get("run_exports", {}).items():
                for p in v:
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


def _create_migration_yaml_creator(
    messages,
    package_name,
    pinning_name,
    current_version,
    current_pin,
    pin_spec,
    feedstock_name,
    pinnings_together,
):
    migrators = []
    try:
        migrators.append(
            MigrationYamlCreator(
                package_name=pinning_name,
                new_pin_version=current_version,
                current_pin=current_pin,
                pin_spec=pin_spec,
                feedstock_name=feedstock_name,
                total_graph=load_existing_graph(),
                pinnings=pinnings_together,
                pr_limit=1,
            )
        )
    except Exception:
        import traceback

        messages.append(f"failed to make pinning migrator for {pinning_name}")
        messages.append("%s:" % pinning_name)
        messages.append("    package name: %s" % package_name)
        messages.append("    feedstock name: %s" % feedstock_name)
        messages.append("    error:\n%s" % traceback.format_exc())

    if messages:
        tqdm.tqdm.write(f"{HEADER} " + "\n".join(messages) + "\n")

    return migrators


def create_migration_yaml_creator(
    pin_to_debug=None,
    pool=None,
):
    gx = load_existing_graph()

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

    migrators_or_futs = []
    for pinning_name in pinning_names:
        if (
            pinning_name in packages_to_migrate_together_mapping
            and pinning_name not in packages_to_migrate_together
        ):
            continue

        if pin_to_debug is not None and pinning_name != pin_to_debug:
            continue

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

        messages = []
        inner_messages = []
        with gx.nodes[feedstock_name]["payload"] as feedstock_attrs:
            if feedstock_attrs.get("archived", False) or not feedstock_attrs.get(
                "version"
            ):
                continue

            package_pin_list = pinnings[pinning_name]

            # there are three things:
            # pinning_name - entry in pinning file
            # package_name - the actual package, could differ via `-` -> `_`
            #                from pinning_name
            # feedstock_name - the feedstock that outputs the package
            # we need the package names for the migrator itself but need the
            # feedstock for everything else

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
                    inner_messages.append(f"making pinning migrator for {pinning_name}")
                    pinnings_together = packages_to_migrate_together.get(
                        pinning_name, [pinning_name]
                    )
                    inner_messages.append("%s:" % pinning_name)
                    inner_messages.append("    package name: %s" % package_name)
                    inner_messages.append("    feedstock name: %s" % feedstock_name)
                    for p in possible_p_dicts:
                        inner_messages.append("    possible pin spec: %s" % p)
                    inner_messages.append(
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
                        )
                    )
                    if pool is None:
                        migrators_or_futs.extend(
                            _create_migration_yaml_creator(
                                inner_messages,
                                package_name,
                                pinning_name,
                                current_version,
                                current_pin,
                                pin_spec,
                                feedstock_name,
                                pinnings_together,
                            )
                        )
                    else:
                        migrators_or_futs.append(
                            pool.submit(
                                _create_migration_yaml_creator,
                                inner_messages,
                                package_name,
                                pinning_name,
                                current_version,
                                current_pin,
                                pin_spec,
                                feedstock_name,
                                pinnings_together,
                            )
                        )
            except Exception:
                import traceback

                messages.append(f"failed to make pinning migrator for {pinning_name}")
                messages.append("%s:" % pinning_name)
                messages.append("    package name: %s" % package_name)
                messages.append("    feedstock name: %s" % feedstock_name)
                messages.append("    error:\n%s" % traceback.format_exc())

        if messages:
            tqdm.tqdm.write(f"{HEADER} " + "\n".join(messages) + "\n")

    return migrators_or_futs


def make_noarch_python_min_migrator():
    migrators = []
    tqdm.tqdm.write(f"{HEADER} making `noarch: python` migrator")
    migrators.append(
        NoarchPythonMinMigrator(
            total_graph=load_existing_graph(),
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

    return migrators


def make_static_lib_migrator():
    migrators = []
    tqdm.tqdm.write(f"{HEADER} making static lib migrator")
    migrators.append(
        StaticLibMigrator(
            total_graph=load_existing_graph(),
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

    return migrators


def make_nvtools_migrator():
    migrators = []
    tqdm.tqdm.write(f"{HEADER} making add nvtools migrator")
    migrators.append(
        AddNVIDIATools(
            check_solvable=False,
            total_graph=load_existing_graph(),
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

    return migrators


def _sort_and_shuffle_migrators(input_migrators):
    migrators = []
    version_migrator = None
    pinning_migrators = []
    longterm_migrators = []
    for migrator in input_migrators:
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

    RNG.shuffle(pinning_migrators)
    RNG.shuffle(longterm_migrators)
    migrators = [version_migrator] + migrators + pinning_migrators + longterm_migrators

    return migrators


def _remove_dup_yaml_creators(migrators):
    seen = set()
    new_migrators = []
    for m in migrators:
        if isinstance(m, MigrationYamlCreator):
            if m.name in seen:
                continue
            seen.add(m.name)
        new_migrators.append(m)
    return new_migrators


def initialize_migrators(
    dry_run: bool = False,
) -> MutableSequence[Migrator]:
    with fold_log_lines("making migrators"), executor("process", 8) as pool:
        futs = []
        futs.extend(
            create_migration_yaml_creator(
                pool=pool,
            )
        )
        futs.append(pool.submit(make_arch_migrators))
        futs.append(
            pool.submit(
                make_replacement_migrator,
                cast("PackageName", "mpir"),
                cast("PackageName", "gmp"),
                "The package 'mpir' is deprecated and unmaintained. Use 'gmp' instead.",
            )
        )
        futs.append(
            pool.submit(
                make_replacement_migrator,
                cast("PackageName", "astropy"),
                cast("PackageName", "astropy-base"),
                "The astropy feedstock has been split into two packages, astropy-base only "
                "has required dependencies and astropy now has all optional dependencies. "
                "To maintain the old behavior you should migrate to astropy-base.",
            )
        )
        futs.append(pool.submit(make_noarch_python_min_migrator))
        futs.append(pool.submit(make_static_lib_migrator))
        futs.append(pool.submit(make_nvtools_migrator))
        futs.extend(migration_factory(pool=pool))

        migrators = []
        for fut in tqdm.tqdm(
            as_completed(futs),
            desc="making migrators",
            ncols=80,
            total=len(futs),
        ):
            migrators.extend(fut.result())

    # for reasons that IDK, this has happened in the past
    # so we correct for it here
    migrators = _remove_dup_yaml_creators(migrators)

    print(f"{HEADER} making version migrator", flush=True)
    print("building package import maps and version migrator", flush=True)
    gx = load_existing_graph()
    python_nodes = {n for n, v in gx.nodes("payload") if "python" in v.get("req", "")}
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
    migrators = [version_migrator] + migrators
    migrators = _sort_and_shuffle_migrators(migrators)

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
    all_names = get_all_keys_for_hashmap("migrators")
    with executor("process", 2) as pool:
        futs = [pool.submit(_load, name) for name in all_names]

        for fut in tqdm.tqdm(
            as_completed(futs), desc="loading migrators", ncols=80, total=len(all_names)
        ):
            migrator = fut.result()

            if getattr(migrator, "paused", False) and skip_paused:
                continue

            migrators.append(migrator)

    return _sort_and_shuffle_migrators(migrators)


def dump_migrators(migrators: MutableSequence[Migrator], dry_run: bool = False) -> None:
    """Dumps the current migrators to JSON.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to dump.
    dry_run : bool, optional
        Whether to perform a dry run, defaults to False. If True, no changes will be made.
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


def main(ctx: CliContext) -> None:
    migrators = initialize_migrators(
        dry_run=ctx.dry_run,
    )
    dump_migrators(
        migrators,
        dry_run=ctx.dry_run,
    )
