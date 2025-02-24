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
    get_keys_default,
    get_migrator_name,
)

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict, MigrationUidTypedDict

RNG = secrets.SystemRandom()
logger = logging.getLogger(__name__)


@lru_cache(maxsize=128)
def get_latest_static_lib(host_req: str, platform_arch: str) -> Dist:
    platform_arch = platform_arch.replace("_", "-")
    rd_fn = fetch_repodata([platform_arch])[0]
    with open(rd_fn) as fp:
        rd = rapidjson.load(fp)
    ms = MatchSpec(host_req)

    max_ver = None
    max_build = None
    max_dist = None
    for key in ["packages", "packages.conda"]:
        for on in rd[key]:
            if on.rsplit("-", 2)[0] == ms.name:
                dist = Dist.from_string(on, channel_override="conda-forge")
                if ms.match(dist):
                    ver = VersionOrder(dist.version)
                    build = dist.build_number

                    if max_ver is None:
                        max_ver = ver
                        max_build = build
                        max_dist = dist
                    elif (ver > max_ver) or (ver == max_ver and build > max_build):
                        max_ver = ver
                        max_build = build
                        max_dist = dist

    if max_dist is None:
        raise ValueError(
            f"Could not find a static lib for {host_req} on {platform_arch}!"
        )
    return max_dist


def any_static_libs_out_of_date(
    static_linking_host_requirements: list[str],
    raw_meta_yaml: str,
    platform_arches: list[str],
) -> bool:
    # for each plat-arch combo, find latest static lib version
    # and compare to meta.yaml
    # if any of them are out of date, return True
    # else return False

    for platform_arch in platform_arches:
        for slhr in static_linking_host_requirements:
            ld = get_latest_static_lib(slhr, platform_arch)
            ldstr = ld.to_match_spec().conda_build_form()
            if ldstr not in raw_meta_yaml:
                return True

    return False


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

            if any_static_libs_out_of_date(
                static_linking_host_requirements=sl_host_req,
                raw_meta_yaml=payload.get("raw_meta_yaml", "") or "",
                platform_arches=payload.get("platforms", []) or [],
            ):
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

        static_libs_out_of_date = any_static_libs_out_of_date(
            static_linking_host_requirements=sl_host_req,
            raw_meta_yaml=attrs.get("raw_meta_yaml", "") or "",
            platform_arches=attrs.get("platforms", []) or [],
        )

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
        # TODO
        # for each plat-arch combo, find latest static lib version
        # and update the meta.yaml if needed

        with pushd(recipe_dir):
            if os.path.exists("recipe.yaml"):
                self.set_build_number("recipe.yaml")
            else:
                self.set_build_number("meta.yaml")

        return super().migrate(recipe_dir, attrs)

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
        return n
