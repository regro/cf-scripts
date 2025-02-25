import logging
import os
import secrets
import typing
from functools import lru_cache
from typing import Any, Optional, Sequence

import networkx as nx
import rapidjson
from conda.models.dist import Dist
from conda.models.match_spec import MatchSpec
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
    get_migrator_name,
)

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict, MigrationUidTypedDict

RNG = secrets.SystemRandom()
logger = logging.getLogger(__name__)


def _left_gt_right_dist(ld, rd):
    lver = VersionOrder(ld.version)
    lbuild = ld.build_number

    rver = VersionOrder(rd.version)
    rbuild = rd.build_number

    if (lver > rver) or (lver == rver and lbuild > rbuild):
        return True
    else:
        return False


@lru_cache(maxsize=128)
def _cached_dist_from_str(req: str) -> Dist:
    return Dist.from_string(req, channel_override="conda-forge")


@lru_cache(maxsize=128)
def _cached_match_spec(req: str) -> MatchSpec:
    return MatchSpec(req)


@lru_cache(maxsize=128)
def _match_spec_is_exact(ms: MatchSpec) -> bool:
    if (
        ms.get_exact_value("name") is not None
        and ms.get_exact_value("version") is not None
        and ms.get_exact_value("build") is not None
    ):
        return True
    else:
        return False


@lru_cache(maxsize=128)
def _match_spec_to_dist(ms: MatchSpec) -> Dist:
    if _match_spec_is_exact(ms):
        mstr = ms.conda_build_form().replace(" ", "-")
        return _cached_dist_from_str(mstr)
    else:
        raise ValueError("MatchSpec is not exact: %s" % ms.conda_build_form())


@lru_cache(maxsize=128)
def get_latest_static_lib(host_req: str, platform_arch: str) -> Dist:
    platform_arch = platform_arch.replace("_", "-")
    rd_fn = fetch_repodata([platform_arch])[0]
    with open(rd_fn) as fp:
        rd = rapidjson.load(fp)
    ms = _cached_match_spec(host_req)

    max_dist = None
    for key in ["packages", "packages.conda"]:
        for fn in rd[key]:
            if fn.rsplit("-", 2)[0] == ms.name:
                dist = _cached_dist_from_str(fn)
                if ms.match(dist):
                    if max_dist is None:
                        max_dist = dist
                    else:
                        if _left_gt_right_dist(dist, max_dist):
                            max_dist = dist

    if max_dist is None:
        raise ValueError(
            f"Could not find a static lib for `{host_req}` on `{platform_arch}`!"
        )
    return max_dist


@lru_cache(maxsize=128)
def platform_has_dist(platform_arch: str, dist: Dist) -> bool:
    platform_arch = platform_arch.replace("_", "-")
    rd_fn = fetch_repodata([platform_arch])[0]
    with open(rd_fn) as fp:
        rd = rapidjson.load(fp)

    fn_dist = "-".join(dist.quad[:3])

    for key in ["packages", "packages.conda"]:
        for fn in rd[key]:
            if fn_dist in fn:
                return True
    return False


def extract_static_libs_from_meta_yaml_text(
    meta_yaml_texts: tuple[str],
    static_linking_host_requirement: str,
    platform_arch: str | None = None,
) -> set[Dist]:
    ms = _cached_match_spec(static_linking_host_requirement)

    dists = set()
    for my in meta_yaml_texts:
        for line in my.splitlines():
            line = line.strip()
            if line.startswith("-"):
                line = line[1:].strip()
                line = line.split("#", maxsplit=1)[0].strip()
                try:
                    rms = _cached_match_spec(line)
                except Exception:
                    logger.debug(
                        "could not parse line: %s into a MatchSpec. It will be ignored!",
                        line,
                    )
                    continue
                if _match_spec_is_exact(rms) and rms.get_exact_value(
                    "name"
                ) == ms.get_exact_value("name"):
                    dist = _match_spec_to_dist(rms)
                    if platform_arch is None or platform_has_dist(platform_arch, dist):
                        dists.add(dist)

    return dists


@lru_cache(maxsize=128)
def any_static_libs_out_of_date(
    static_linking_host_requirements: tuple[str],
    platform_arches: tuple[str],
    raw_meta_yaml: str,
) -> (bool, dict[str, dict[str, str]]):
    # for each plat-arch combo, find latest static lib version
    # and compare to meta.yaml
    # if any of them are out of date, return True
    # else return False
    # also require that all latest static libs
    # have the same version and build number
    host_sections = extract_section_from_yaml_text(raw_meta_yaml, "host")

    static_lib_replacements = {}
    for platform_arch in platform_arches:
        static_lib_replacements[platform_arch] = {}

    out_of_date = False
    for slhr in static_linking_host_requirements:
        curr_ver_build = (None, None)
        for platform_arch in platform_arches:
            ld = get_latest_static_lib(slhr, platform_arch)

            # if we find different versions, we bail since there
            # could be a race condition or something else going on
            if curr_ver_build == (None, None):
                curr_ver_build = (ld.version, ld.build_number)
            elif curr_ver_build != (ld.version, ld.build_number):
                return False, static_lib_replacements

            ldstr = ld.to_match_spec().conda_build_form()

            # test if version in meta_yaml is less than version we found
            # if so, set out_of_date = True
            # always add static lib from recipe to old_static_libs
            _old_dists = extract_static_libs_from_meta_yaml_text(
                host_sections,
                slhr,
                platform_arch,
            )
            for _old_dist in _old_dists:
                # add to set of replacements if needs update
                if _left_gt_right_dist(ld, _old_dist):
                    out_of_date = True
                    odstr = _old_dist.to_match_spec().conda_build_form()
                    static_lib_replacements[platform_arch][odstr] = ldstr

    return out_of_date, static_lib_replacements


def attempt_update_static_libs(
    raw_meta_yaml: str,
    static_lib_replacements: dict[str, dict[str, str]],
) -> (bool, str):
    """Attempt to update static lib versions in meta.yaml.

    Returns True if the recipe was updated, False otherwise.
    Also returns the new recipe.
    """
    updated = False

    for plat_arch in static_lib_replacements:
        for old_spec, new_spec in static_lib_replacements[plat_arch].items():
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
    name = "static-lib-migrator"

    def __init__(
        self,
        graph: nx.DiGraph = None,
        pr_limit: int = 0,
        bump_number: int = 1,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
        check_solvable=True,
        max_solver_attempts=3,
        effective_graph: nx.DiGraph = None,
        force_pr_after_solver_attempts=10,
        longterm=False,
        paused=False,
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
                "max_solver_attempts": max_solver_attempts,
                "effective_graph": effective_graph,
                "longterm": longterm,
                "force_pr_after_solver_attempts": force_pr_after_solver_attempts,
                "paused": paused,
            }

        super().__init__(
            graph=graph,
            pr_limit=pr_limit,
            obj_version=0,
            piggy_back_migrations=piggy_back_migrations,
            check_solvable=check_solvable,
            effective_graph=effective_graph,
        )
        self.top_level = set()
        self.cycles = set()
        self.bump_number = bump_number
        self.max_solver_attempts = max_solver_attempts
        self.longterm = longterm
        self.force_pr_after_solver_attempts = force_pr_after_solver_attempts
        self.paused = paused

        self._reset_effective_graph()

    def predecessors_not_yet_built(self, attrs: "AttrsTypedDict") -> bool:
        # Check if all upstreams have been built
        for node, payload in _gen_active_feedstocks_payloads(
            self.graph.predecessors(attrs["feedstock_name"]),
            self.graph,
        ):
            sl_host_req = get_keys_default(
                payload,
                ["meta_yaml", "extra", "static_linking_host_requirements"],
                dict(),
                list(),
            )

            if len(sl_host_req) == 0:
                continue

            platform_arches = tuple(payload.get("platforms", []) or [])
            if any_static_libs_out_of_date(
                static_linking_host_requirements=tuple(sl_host_req),
                platform_arches=platform_arches,
                raw_meta_yaml=payload.get("raw_meta_yaml", "") or "",
            )[0]:
                logger.debug("not yet built for new static libs: %s" % node)
                return True

        return False

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """Determine whether feedstock needs to be filtered out.

        Return True to skip ("filter") the feedstock from the migration.
        Return False to include the feedstock in the migration.
        """

        sl_host_req = get_keys_default(
            attrs,
            ["meta_yaml", "extra", "static_linking_host_requirements"],
            dict(),
            list(),
        )
        has_static_libs = len(sl_host_req) > 0
        logger.debug(
            "filter %s: no static libs: %s",
            attrs.get("name", ""),
            sl_host_req,
        )
        if not has_static_libs:
            return True

        platform_arches = tuple(attrs.get("platforms", []) or [])
        static_libs_out_of_date = any_static_libs_out_of_date(
            static_linking_host_requirements=tuple(sl_host_req),
            platform_arches=platform_arches,
            raw_meta_yaml=attrs.get("raw_meta_yaml", "") or "",
        )[0]

        return (
            (not has_static_libs)
            or (not static_libs_out_of_date)
            or super().filter(
                attrs=attrs,
                not_bad_str_start=not_bad_str_start,
            )
        )

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        # for each plat-arch combo, find latest static lib version
        # and update the meta.yaml if needed
        sl_host_req = get_keys_default(
            attrs,
            ["meta_yaml", "extra", "static_linking_host_requirements"],
            dict(),
            list(),
        )
        platform_arches = tuple(attrs.get("platforms", []) or [])

        with pushd(recipe_dir):
            if os.path.exists("recipe.yaml"):
                with open("recipe.yaml") as f:
                    raw_meta_yaml = f.read()
            else:
                with open("meta.yaml") as f:
                    raw_meta_yaml = f.read()

        needs_update, static_lib_replacements = any_static_libs_out_of_date(
            static_linking_host_requirements=tuple(sl_host_req),
            platform_arches=platform_arches,
            raw_meta_yaml=raw_meta_yaml,
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
                    "static libs not updated for feedstock '%s' for host requirements '%s'",
                    attrs.get("feedstock_name", "!!NONAME!!"),
                    sl_host_req,
                )
        muid = super().migrate(recipe_dir, attrs)
        if not needs_update:
            muid["already_done"] = True

        return muid

    def pr_body(self, feedstock_ctx: ClonedFeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        name = get_migrator_name(self)
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
            "the your rebuild has been merged.**\n\n"
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
        # prevents duplicate PRs or missed PRs
        # get_latest_static_libs caches the results so the return value
        # is stable for a given execution of the bot
        platform_arches = tuple(attrs.get("platforms", []) or [])
        sl_host_req = get_keys_default(
            attrs,
            ["meta_yaml", "extra", "static_linking_host_requirements"],
            dict(),
            list(),
        )
        vals = []
        for slhr in sl_host_req:
            for platform_arch in platform_arches:
                ld = get_latest_static_lib(slhr, platform_arch)
                ldstr = ld.to_match_spec().conda_build_form()
                ldstr = "::".join([platform_arch.replace("_", "-"), ldstr])
                vals.append(ldstr)
        ustr = ";".join(sorted(vals))
        n["static_libs"] = ustr

        return n
