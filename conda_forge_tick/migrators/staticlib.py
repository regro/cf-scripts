import copy
import logging
import os
import re
import secrets
import time
import typing
from functools import lru_cache
from typing import Any, Optional, Sequence

import networkx as nx
import orjson
from conda.models.match_spec import MatchSpec
from conda.models.records import PackageRecord
from conda.models.version import VersionOrder
from conda_forge_metadata.repodata import fetch_repodata

from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.migrators.core import (
    GraphMigrator,
    MiniMigrator,
    _gen_active_feedstocks_payloads,
)
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import (
    extract_section_from_yaml_text,
    get_keys_default,
    get_recipe_schema_version,
)

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict, MigrationUidTypedDict

BUILD_STRING_END_RE = re.compile(r".*_\d+$")

RNG = secrets.SystemRandom()

logger = logging.getLogger(__name__)


def _left_gt_right_rec(lrec, rrec):
    """Compare two records, declaring the left one bigger if
    the version and/or build number is bigger.
    """
    lver = VersionOrder(lrec.version)
    lbuild = lrec.build_number
    rver = VersionOrder(rrec.version)
    rbuild = rrec.build_number

    if (lver > rver) or (lver == rver and lbuild > rbuild):
        return True
    else:
        return False


@lru_cache(maxsize=128)
def _cached_match_spec(req: str | MatchSpec) -> MatchSpec:
    return MatchSpec(req)


@lru_cache(maxsize=1)
def _read_repodata(platform_arch: str) -> Any:
    rd = None
    platform_arch = platform_arch.replace("_", "-")
    for i in range(10):
        try:
            rd_fn = fetch_repodata([platform_arch])[0]
            with open(rd_fn) as fp:
                rd = orjson.loads(fp.read())
        except Exception:
            time.sleep((0.1 * 2**i) + RNG.uniform(0, 0.1))
            continue
        else:
            break

    if rd is None:
        raise RuntimeError(f"Download of repodata for {platform_arch} failed!")

    return rd


@lru_cache(maxsize=128)
def get_latest_static_lib(host_req: str, platform_arch: str) -> PackageRecord | None:
    """Get the latest PackageRecord for a given abstract requirement.

    Returns None if no matching record is found.

    Parameters
    ----------
    host_req: str
        The abstract requirement to match.
    platform_arch: str
        The platform architecture to match (e.g., 'osx-arm64').

    Returns
    -------
    PackageRecord | None
        The latest PackageRecord that matches the requirement.
    """
    platform_arch = platform_arch.replace("_", "-")
    rd = _read_repodata(platform_arch)
    ms = _cached_match_spec(host_req)

    max_rec = None
    for key in ["packages", "packages.conda"]:
        for fn, rec in rd[key].items():
            if rec["name"] == ms.name:
                rec = PackageRecord(**rec)
                if ms.match(rec):
                    if max_rec is None:
                        max_rec = rec
                    else:
                        if _left_gt_right_rec(rec, max_rec):
                            max_rec = rec

    return max_rec


@lru_cache(maxsize=128)
def is_abstract_static_lib_spec(ms: str | MatchSpec) -> bool:
    """Determine if a MatchSpec is an abstract static lib spec.

    To be concrete, it has to have a name, version, and build string
    pinned down to the build number (which must come last).

    Anything not concrete is abstract.
    """
    ms = _cached_match_spec(ms)

    if ms.get_exact_value("name") is None:
        return True

    if ms.get_exact_value("version") is None:
        return True

    bld = ms.get_raw_value("build")
    if bld is None or (not bld) or (not BUILD_STRING_END_RE.match(bld)):
        return True

    # if we get there, it is a concrete spec
    return False


@lru_cache(maxsize=128)
def extract_static_lib_specs_from_raw_meta_yaml(
    raw_meta_yaml: str,
) -> dict[str, dict[str, set[str]]]:
    """Extract static lib specs from the meta.yaml file.

    For a set of specs that refer to the same package to be a
    static lib spec we need that

    - at least one of the specs must be pinned down to the build number
    - at least one of the specs must not be pinned down to the build number

    The second of these is an "abstract" spec and the first is a "concrete" spec.
    The highest version + build number package that matches the abstract spec is the
    concrete spec.

    The return value is a dictionary that maps the package name to a dictionary of sets
    of concrete and abstract specs:

        {"foo": {"abstract": {"foo 1.0.*"}, "concrete": {"foo 1.0.0 h4541_5"}}}
    """
    all_specs_by_name = {}

    # divide recipe into host sections
    for host_section in extract_section_from_yaml_text(raw_meta_yaml, "host"):
        for line in host_section.splitlines():
            line = line.strip()
            if (
                line.startswith("-")
                or line.startswith("then:")
                or line.startswith("else:")
            ):
                if line.startswith("-"):
                    line = line[1:].strip()
                elif line.startswith("then:") or line.startswith("else:"):
                    line = line[5:].strip()
                line = line.split("#", maxsplit=1)[0].strip()
                try:
                    rms = _cached_match_spec(line)
                except Exception:
                    logger.debug(
                        "could not parse line: %s into a MatchSpec. It will be ignored!",
                        line,
                    )
                    continue

                orig_spec = line
                nm = rms.get_exact_value("name")

                if nm is None:
                    logger.debug(
                        "skipping spec due to name issue: '%s'",
                        orig_spec,
                    )
                    continue

                if nm not in all_specs_by_name:
                    all_specs_by_name[nm] = {"abstract": set(), "concrete": set()}

                if is_abstract_static_lib_spec(rms):
                    all_specs_by_name[nm]["abstract"].add(orig_spec)
                else:
                    all_specs_by_name[nm]["concrete"].add(orig_spec)

    nms = list(all_specs_by_name.keys())
    for nm in nms:
        spec_dict = all_specs_by_name[nm]
        # if we don't have at least one abstract and one concrete spec
        # then it is not a static lib spec so remove it
        if not (spec_dict["abstract"] and spec_dict["concrete"]):
            del all_specs_by_name[nm]

    return all_specs_by_name


def _munge_hash_matchspec(ms: str) -> str:
    """Replace any hash part of a build string with a wildcard.

    This function assumes the hash part always starts with `h`
    and is 8 characters long, and is separated by underscores
    from the rest of the build string.
    """
    parts = ms.split(" ")
    bparts = parts[2].split("_")
    new_bparts = []
    for bpart in bparts:
        if bpart.startswith("h") and len(bpart) == 8:
            bpart = "*"
        new_bparts.append(bpart)
    parts[2] = "_".join(new_bparts)
    return " ".join(parts)


@lru_cache(maxsize=128)
def any_static_libs_out_of_date(
    platform_arches: tuple[str],
    raw_meta_yaml: str,
    schema_version: int = 0,
) -> (bool, dict[str, dict[str, str]]):
    """Check if any static libs are out of date for a given recipe and set of platforms.

    Parameters
    ----------
    platform_arches: tuple[str]
        The platform architectures to check (e.g., 'osx-arm64').
    raw_meta_yaml: str
        The raw meta.yaml file to check.

    Returns
    -------
    out_of_date : bool
        If True, the static lib is out of date.
    static_lib_replacements : dict[str, dict[str, str]]
        A dictionary mapping platform architectures to dictionaries
        of concrete specs and their updated replacements:

        {"osx-arm64": {"llvm 13 *_5": "llvm 13 *_6"}}
    """
    # for each plat-arch combo, find latest static lib version
    # and compare to meta.yaml
    # if any of them are out of date, return True
    # else return False
    # also require that all latest static libs
    # have the same version and build number
    all_specs_by_name = extract_static_lib_specs_from_raw_meta_yaml(
        raw_meta_yaml,
    )
    logger.debug(
        "static lib specs found in meta.yaml: %s",
        all_specs_by_name,
    )

    static_lib_replacements = {}
    for platform_arch in platform_arches:
        static_lib_replacements[platform_arch] = {}

    out_of_date = False
    for name, spec_dict in all_specs_by_name.items():
        curr_ver_build = (None, None)
        for abs_spec in spec_dict["abstract"]:
            for platform_arch in platform_arches:
                latest_rec = get_latest_static_lib(abs_spec, platform_arch)
                logger.debug(
                    "latest static lib for spec '%s' on platform '%s': %s",
                    abs_spec,
                    platform_arch,
                    latest_rec.to_match_spec().conda_build_form(),
                )

                # if we find different versions, we bail since there
                # could be a race condition or something else going on
                if curr_ver_build == (None, None):
                    curr_ver_build = (latest_rec.version, latest_rec.build_number)
                elif curr_ver_build != (latest_rec.version, latest_rec.build_number):
                    return False, static_lib_replacements

                latest_str = latest_rec.to_match_spec().conda_build_form()

                for conc_spec in spec_dict["concrete"]:
                    conc_rec = get_latest_static_lib(conc_spec, platform_arch)
                    if conc_rec is None:
                        continue
                    logger.debug(
                        "latest concrete static lib for spec '%s' on platform '%s': %s",
                        conc_spec,
                        platform_arch,
                        conc_rec.to_match_spec().conda_build_form(),
                    )

                    # add to set of replacements if needs update
                    if _left_gt_right_rec(latest_rec, conc_rec):
                        logger.debug(
                            "static lib '%s' is out of date: %s",
                            conc_rec.to_match_spec().conda_build_form(),
                            latest_rec.to_match_spec().conda_build_form(),
                        )
                        out_of_date = True

                        # this is a concrete spec with a build number at the
                        # end of the build string, so we can test for wildcard
                        # by simply string manipulation

                        if "*_" in conc_spec.split(" ")[-1]:
                            final_latest_str = _munge_hash_matchspec(latest_str)
                        else:
                            final_latest_str = latest_str

                        # for v1 recipes we use exact versions
                        if schema_version == 1:
                            parts = final_latest_str.split(" ")
                            final_latest_str = " ".join(
                                [parts[0], "==" + parts[1], parts[2]]
                            )

                        static_lib_replacements[platform_arch][conc_spec] = (
                            final_latest_str
                        )

    return out_of_date, static_lib_replacements


def attempt_update_static_libs(
    raw_meta_yaml: str,
    static_lib_replacements: dict[str, dict[str, str]],
) -> (bool, str):
    """Attempt to update static lib versions in meta.yaml.

    Parameters
    ----------
    raw_meta_yaml: str
        The raw meta.yaml file to update.
    static_lib_replacements: dict[str, dict[str, str]]
        A dictionary mapping platform architectures to dictionaries
        of concrete specs and their updated replacements:

        {"osx-arm64": {"llvm 13 *_5": "llvm 13 *_6"}}

    Returns
    -------
    updated : bool
        If True, the recipe was updated.
    new_raw_meta_yaml : str
        The updated raw meta.yaml file.
    """
    updated = False

    logger.debug(
        "attempting to update static libs in meta.yaml: %s",
        static_lib_replacements,
    )

    for do_globs in [False, True]:
        for plat_arch in static_lib_replacements:
            # ensure exact specs come before ones with globs
            for old_spec, new_spec in static_lib_replacements[plat_arch].items():
                if not do_globs and "*" in old_spec:
                    continue

                new_raw_meta_yaml = raw_meta_yaml.replace(
                    old_spec,
                    new_spec,
                )
                if new_raw_meta_yaml != raw_meta_yaml:
                    updated = True
                    raw_meta_yaml = new_raw_meta_yaml
                    logger.debug(
                        "static lib '%s' updated to '%s'",
                        old_spec,
                        new_spec,
                    )

    return updated, raw_meta_yaml


class StaticLibMigrator(GraphMigrator):
    """Migrator for bumping static library host dependencies."""

    migrator_version = 0
    rerender = True
    allowed_schema_versions = [0, 1]

    def __init__(
        self,
        graph: nx.DiGraph | None = None,
        pr_limit: int = 0,
        bump_number: int = 1,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
        check_solvable=True,
        effective_graph: nx.DiGraph | None = None,
        force_pr_after_solver_attempts=10,
        longterm=False,
        paused=False,
        total_graph: nx.DiGraph | None = None,
    ):
        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "graph": graph,
                "pr_limit": pr_limit,
                "bump_number": bump_number,
                "piggy_back_migrations": piggy_back_migrations,
                "check_solvable": check_solvable,
                "effective_graph": effective_graph,
                "longterm": longterm,
                "force_pr_after_solver_attempts": force_pr_after_solver_attempts,
                "paused": paused,
                "total_graph": total_graph,
            }

        self.top_level = set()
        self.cycles = set()
        self.bump_number = bump_number
        self.longterm = longterm
        self.force_pr_after_solver_attempts = force_pr_after_solver_attempts
        self.paused = paused

        if total_graph is not None:
            total_graph = copy.deepcopy(total_graph)
            total_graph.clear_edges()

        super().__init__(
            graph=graph,
            pr_limit=pr_limit,
            obj_version=0,
            piggy_back_migrations=piggy_back_migrations,
            check_solvable=check_solvable,
            effective_graph=effective_graph,
            name="static_lib_migrator",
            total_graph=total_graph,
        )

    def predecessors_not_yet_built(self, attrs: "AttrsTypedDict") -> bool:
        # Check if all upstreams have been built
        for node, payload in _gen_active_feedstocks_payloads(
            self.graph.predecessors(attrs["feedstock_name"]),
            self.graph,
        ):
            update_static_libs = get_keys_default(
                payload,
                ["conda-forge.yml", "bot", "update_static_libs"],
                {},
                False,
            )

            if not update_static_libs:
                continue

            platform_arches = tuple(payload.get("platforms") or [])
            if any_static_libs_out_of_date(
                platform_arches=platform_arches,
                raw_meta_yaml=payload.get("raw_meta_yaml") or "",
            )[0]:
                logger.debug("not yet built for new static libs: %s", node)
                return True

        return False

    def filter_not_in_migration(self, attrs, not_bad_str_start=""):
        if super().filter_not_in_migration(attrs, not_bad_str_start):
            return True

        update_static_libs = get_keys_default(
            attrs,
            ["conda-forge.yml", "bot", "update_static_libs"],
            {},
            False,
        )

        if not update_static_libs:
            logger.debug(
                "filter %s: static lib updates not enabled",
                attrs.get("name") or "",
            )

        if update_static_libs:
            platform_arches = tuple(attrs.get("platforms") or [])
            static_libs_out_of_date, slrep = any_static_libs_out_of_date(
                platform_arches=platform_arches,
                raw_meta_yaml=attrs.get("raw_meta_yaml") or "",
            )
            if not static_libs_out_of_date:
                logger.debug(
                    "filter %s: no static libs out of date\nmapping: %s",
                    attrs.get("name") or "",
                    slrep,
                )
            _read_repodata.cache_clear()
        else:
            static_libs_out_of_date = False

        return (not update_static_libs) or (not static_libs_out_of_date)

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        # for each plat-arch combo, find latest static lib version
        # and update the meta.yaml if needed
        platform_arches = tuple(attrs.get("platforms") or [])

        with pushd(recipe_dir):
            if os.path.exists("recipe.yaml"):
                with open("recipe.yaml") as f:
                    raw_meta_yaml = f.read()
            else:
                with open("meta.yaml") as f:
                    raw_meta_yaml = f.read()

        schema_version = get_recipe_schema_version(attrs)

        needs_update, static_lib_replacements = any_static_libs_out_of_date(
            platform_arches=platform_arches,
            raw_meta_yaml=raw_meta_yaml,
            schema_version=schema_version,
        )

        if needs_update:
            updated_recipe, new_raw_meta_yaml = attempt_update_static_libs(
                raw_meta_yaml=raw_meta_yaml,
                static_lib_replacements=static_lib_replacements,
            )

            if updated_recipe:
                with pushd(recipe_dir):
                    if os.path.exists("recipe.yaml"):
                        with open("recipe.yaml", "w") as f:
                            f.write(new_raw_meta_yaml)
                        self.set_build_number("recipe.yaml")
                    else:
                        with open("meta.yaml", "w") as f:
                            f.write(new_raw_meta_yaml)
                        self.set_build_number("meta.yaml")
            else:
                needs_update = False
                logger.debug(
                    "static libs not updated for feedstock '%s' for static libs '%s'",
                    attrs.get("feedstock_name") or "!!NONAME!!",
                    {k.split(" ")[0] for k in static_lib_replacements.keys()},
                )
        muid = super().migrate(recipe_dir, attrs)
        if not needs_update:
            muid["already_done"] = True

        _read_repodata.cache_clear()
        return muid

    def pr_body(self, feedstock_ctx: ClonedFeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        name = self.report_name
        url = f"https://conda-forge.org/status/migration/?name={name}"
        additional_body = (
            "This PR has been triggered in an effort to update "
            f"[**statically linked libraries**]({url}).\n\n"
            "Notes and instructions for merging this PR:\n"
            "1. Please merge the PR only after the tests have passed. \n"
            "2. Feel free to push to the bot's branch to update this PR "
            "if needed. \n\n"
            "**Please note that if you close this PR we presume that "
            "the feedstock has been rebuilt, so if you are going to "
            "perform the rebuild yourself don't close this PR until "
            "the rebuild has been merged.**\n\n"
            "<hr>"
            "".format(
                name=name,
                url=url,
            )
        )

        return body.format(additional_body)

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return "Rebuild for static library updates"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return self.commit_message(feedstock_ctx).splitlines()[0]

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        s_obj = str(self.obj_version) if self.obj_version else ""
        return f"rebuild-{self.name.lower().replace(' ', '_')}-{self.migrator_version}-{s_obj}"  # noqa

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        n = super().migrator_uid(attrs)
        n["name"] = self.name

        # build a unique string from the latest static libs found
        # from the abstract specs
        # prevents duplicate PRs or missed PRs
        # _get_latest_static_lib caches the results so the return value
        # is stable for a given execution of the bot
        platform_arches = tuple(attrs.get("platforms") or [])
        all_specs_by_name = extract_static_lib_specs_from_raw_meta_yaml(
            attrs.get("raw_meta_yaml") or "",
        )
        vals = []
        for platform_arch in platform_arches:
            for spec_dict in all_specs_by_name.values():
                for abs_spec in spec_dict["abstract"]:
                    rec = get_latest_static_lib(abs_spec, platform_arch)
                    rec = rec.to_match_spec().conda_build_form()
                    rec = "::".join([platform_arch.replace("_", "-"), rec])
                    vals.append(rec)
        ustr = ";".join(sorted(vals))
        n["static_libs"] = ustr

        return n
