import copy
import logging
import os
import re
import secrets
import time
from collections import defaultdict
from typing import Any, Collection, Literal, Optional, Sequence, Set

import networkx as nx

from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.feedstock_parser import PIN_SEP_PAT
from conda_forge_tick.make_graph import get_deps_from_outputs_lut
from conda_forge_tick.migrators.core import (
    GraphMigrator,
    Migrator,
    MiniMigrator,
    get_outputs_lut,
)
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import (
    get_bot_run_url,
    get_keys_default,
    yaml_safe_dump,
    yaml_safe_load,
)

from ..migrators_types import AttrsTypedDict, MigrationUidTypedDict, PackageName

RNG = secrets.SystemRandom()
logger = logging.getLogger(__name__)


def _patch_dict(cfg, patches):
    """Patch a dictionary using a set of patches.

    Given a dict like

        {"a": 10, "b": {"c": 15}}

    a patch like this

        {"a": [11, 12], "b.c": 20}

    will produce

        {"a": [11, 12], "b": {"c": 20}}

    Note that whole keys are replaced whereas keys separated by periods
    specify a path to a key.

    Parameters
    ----------
    cfg : dict
        The input dictionary to be patched in place.
    patches : dict
        The dictionary of patches.
    """
    for k, v in patches.items():
        cfg_ref = cfg

        # get the path and key
        # note we reverse the path since we are popping off keys
        # and need to use the first one in the input path
        parts = k.split(".")
        pth = parts[:-1][::-1]
        last_key = parts[-1]

        # go through the path, popping off keys and descending into the dict
        while len(pth) > 0:
            _k = pth.pop()
            if _k in cfg_ref:
                cfg_ref = cfg_ref[_k]
            else:
                break
        # if it all worked, then pth is length zero and the last_key is in
        # the dict, so replace
        if len(pth) == 0 and last_key in cfg_ref:
            cfg_ref[last_key] = v
        else:
            logger.warning("conda-forge.yml patch %s: %s did not work!", k, v)


def merge_migrator_cbc(migrator_yaml: str, conda_build_config_yaml: str):
    """Merge a migrator_yaml with the conda_build_config_yaml."""
    migrator_keys = defaultdict(list)
    current_key = None
    regex = re.compile(r"\w")
    for line in migrator_yaml.split("\n"):
        if not line or line.isspace():
            continue
        if regex.match(line) or line.startswith("_"):
            current_key = line.split()[0]
        # fix for bad indentation from bot's PRs
        if line.startswith("-"):
            line = "  " + line
        migrator_keys[current_key].append(line)

    outbound_cbc = []
    current_cbc_key = None
    for line in conda_build_config_yaml.split("\n"):
        # if we start with a word/underscore we are starting a section
        if regex.match(line) or line.startswith("_") or line.startswith("#"):
            current_cbc_key = line.split()[0]
            # if we are in a section from the migrator use the migrator data
            if current_cbc_key in migrator_keys:
                outbound_cbc.extend(migrator_keys[line.split()[0]])
            else:
                outbound_cbc.append(line)
        # if this is in a key we didn't migrate, add the line (or it is a space)
        elif current_cbc_key not in migrator_keys or line.isspace() or not line:
            outbound_cbc.append(line)
    if outbound_cbc and outbound_cbc[-1]:
        # ensure trailing newline
        outbound_cbc.append("")
    return "\n".join(outbound_cbc)


def _trim_edges_for_abi_rebuild(
    total_graph: nx.DiGraph, migrator: Migrator, outputs_lut: dict[str, str]
) -> nx.DiGraph:
    migrator_payload = migrator.loaded_yaml.get("__migrator", {})
    include_build = migrator_payload.get("include_build", False)

    for node, node_attrs in total_graph.nodes.items():
        # do not trim any edges for pinnings repo
        if node == "conda-forge-pinning":
            continue

        with node_attrs["payload"] as attrs:
            in_migration = not migrator.filter_not_in_migration(attrs)

            requirements = attrs.get("requirements", {})
            host = requirements.get("host", set())
            build = requirements.get("build", set())
            if include_build:
                bh = host | build
            else:
                bh = host or build

            # get host/build, run and test and launder them through outputs
            # this should fix outputs related issues (eg gdal)
            all_reqs = requirements.get("run", set())
            if in_migration:
                all_reqs = all_reqs | requirements.get("test", set())
                all_reqs = all_reqs | bh
            rq = get_deps_from_outputs_lut(
                all_reqs,
                outputs_lut,
            )

            for e in list(total_graph.in_edges(node)):
                if e[0] not in rq:
                    total_graph.remove_edge(*e)

    return total_graph


class MigrationYaml(GraphMigrator):
    """Migrator for bumping the build number."""

    migrator_version = 0
    rerender = True
    allowed_schema_versions = [0, 1]

    # TODO: add a description kwarg for the status page at some point.
    # TODO: make yaml_contents an arg?
    def __init__(
        self,
        yaml_contents: str,
        name: str,
        package_names: set[str] | None = None,
        total_graph: nx.DiGraph | None = None,
        graph: nx.DiGraph | None = None,
        pr_limit: int = 0,
        top_level: Set["PackageName"] | None = None,
        cycles: Optional[Collection["PackageName"]] = None,
        migration_number: Optional[int] = None,
        bump_number: int = 1,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
        automerge: bool = False,
        check_solvable=True,
        conda_forge_yml_patches=None,
        ignored_deps_per_node=None,
        effective_graph: nx.DiGraph | None = None,
        force_pr_after_solver_attempts=10,
        longterm=False,
        paused=False,
        **kwargs: Any,
    ):
        if not hasattr(self, "_init_args"):
            self._init_args = [yaml_contents, name]

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "total_graph": total_graph,
                "graph": graph,
                "pr_limit": pr_limit,
                "top_level": top_level,
                "cycles": cycles,
                "migration_number": migration_number,
                "bump_number": bump_number,
                "piggy_back_migrations": piggy_back_migrations,
                "automerge": automerge,
                "check_solvable": check_solvable,
                "conda_forge_yml_patches": conda_forge_yml_patches,
                "ignored_deps_per_node": ignored_deps_per_node,
                "effective_graph": effective_graph,
                "longterm": longterm,
                "force_pr_after_solver_attempts": force_pr_after_solver_attempts,
                "paused": paused,
                "package_names": package_names,
            }
            self._init_kwargs.update(copy.deepcopy(kwargs))

        self.yaml_contents = yaml_contents
        assert isinstance(name, str)
        self.top_level = top_level or set()
        self.cycles = set(cycles or [])
        self.automerge = automerge
        self.conda_forge_yml_patches = conda_forge_yml_patches
        self.loaded_yaml = yaml_safe_load(self.yaml_contents)
        self.bump_number = bump_number
        self.longterm = longterm
        self.force_pr_after_solver_attempts = force_pr_after_solver_attempts
        self.paused = paused
        self.package_names = package_names or set()

        # special init steps to be done on total_graph
        # - compute package names to find in host to indicate needs migration
        # - trim edges to only those for host|run|test deps - must be done before plucking
        # - add pinning as child of all nodes in graph
        if total_graph is not None:
            # compute package names for migrating
            migrator_payload = self.loaded_yaml.get("__migrator", {})
            all_package_names = set(
                sum(
                    (
                        list(node.get("payload", {}).get("outputs_names", set()))
                        for node in total_graph.nodes.values()
                    ),
                    [],
                ),
            )
            if "override_cbc_keys" in migrator_payload:
                package_names = set(migrator_payload.get("override_cbc_keys"))
            else:
                package_names = (
                    set(self.loaded_yaml)
                    | {ly.replace("_", "-") for ly in self.loaded_yaml}
                ) & all_package_names
            self.package_names = package_names
            self._init_kwargs["package_names"] = package_names

        # compute excluded pinned feedstocks no matter what
        outputs_lut = get_outputs_lut(total_graph, graph, effective_graph)

        self.excluded_pinned_feedstocks = set()
        for _node in self.package_names:
            self.excluded_pinned_feedstocks.update(outputs_lut.get(_node, {_node}))

        # finish special init steps
        if total_graph is not None:
            # needed so that we can filter nodes not in migration
            self.graph = None
            total_graph = copy.deepcopy(total_graph)
            self.total_graph = total_graph
            _trim_edges_for_abi_rebuild(total_graph, self, outputs_lut)
            total_graph.add_edges_from(
                [(n, "conda-forge-pinning") for n in total_graph.nodes]
            )
            delattr(self, "total_graph")
            delattr(self, "graph")

        super().__init__(
            graph=graph,
            pr_limit=pr_limit,
            obj_version=migration_number,
            piggy_back_migrations=piggy_back_migrations,
            check_solvable=check_solvable,
            ignored_deps_per_node=ignored_deps_per_node,
            effective_graph=effective_graph,
            total_graph=total_graph,
            name=name,
        )

        if total_graph is not None:
            # recompute top-level nodes and cycles after cutting to graph of all rebuilds
            # these computations have to go after the call to super which turns the
            # total graph into the graph of all possible rebuilds (stored in self.graph)
            migrator_payload = self.loaded_yaml.get("__migrator", {})
            excluded_feedstocks = set(migrator_payload.get("exclude", []))
            feedstock_names = {
                p for p in self.excluded_pinned_feedstocks if p in total_graph.nodes
            } - excluded_feedstocks

            top_level = {
                node
                for node in {
                    total_graph.successors(feedstock_name)
                    for feedstock_name in feedstock_names
                }
                if (node in self.graph)
                and len(list(self.graph.predecessors(node))) == 0
            }

            cycles = set()
            for cyc in nx.simple_cycles(self.graph):
                cycles |= set(cyc)

            self.top_level = self.top_level | top_level
            self._init_kwargs["top_level"] = top_level
            self.cycles = self.cycles | cycles
            self._init_kwargs["cycles"] = cycles

    def filter_not_in_migration(self, attrs, not_bad_str_start=""):
        if super().filter_not_in_migration(attrs, not_bad_str_start):
            return True

        node = attrs["feedstock_name"]

        if node == "conda-forge-pinning":
            # conda-forge-pinning is always included in migration
            return False

        migrator_payload = self.loaded_yaml.get("__migrator", {})
        include_noarch = migrator_payload.get("include_noarch", False)
        include_build = migrator_payload.get("include_build", False)
        excluded_feedstocks = set(migrator_payload.get("exclude", []))
        exclude_pinned_pkgs = migrator_payload.get("exclude_pinned_pkgs", True)

        # Generally, the packages themselves should be excluded from the migration;
        # an example for exceptions are migrations for new python versions
        # where numpy needs to be rebuilt despite being pinned.
        if exclude_pinned_pkgs:
            excluded_feedstocks.update(self.excluded_pinned_feedstocks)

        requirements = attrs.get("requirements", {})
        host = requirements.get("host", set())
        build = requirements.get("build", set())
        if include_build:
            bh = host | build
        else:
            bh = host or build
        only_python = "python" in self.package_names
        inclusion_criteria = bh & set(self.package_names) and (
            include_noarch or not all_noarch(attrs, only_python=only_python)
        )

        if not inclusion_criteria:
            logger.debug(
                "filter %s: pin %s not in host/build %s",
                node,
                self.package_names,
                bh,
            )

        platform_allowlist = migrator_payload.get("platform_allowlist", [])
        platform_filtered = False
        if platform_allowlist:
            # migrator.platform_allowlist allows both styles: "osx-64" & "osx_64";
            # before comparison, normalize to consistently use underscores (we get
            # "_" in attrs.platforms from the feedstock_parser)
            platform_allowlist = [x.replace("-", "_") for x in platform_allowlist]
            # filter out nodes where the intersection between
            # attrs.platforms and platform_allowlist is empty
            intersection = set(attrs.get("platforms", {})) & set(platform_allowlist)
            platform_filtered = not bool(intersection)

            if platform_filtered:
                logger.debug(
                    "filter %s: platform(s) %s not in %s",
                    node,
                    attrs.get("platforms", {}),
                    platform_allowlist,
                )

        if node in excluded_feedstocks:
            logger.debug(
                "filter %s: excluded feedstock",
                node,
            )

        return (
            platform_filtered
            or (not inclusion_criteria)
            or (node in excluded_feedstocks)
        )

    def filter_node_migrated(self, attrs, not_bad_str_start=""):
        migrator_payload = self.loaded_yaml.get("__migrator", {})
        wait_for_migrators = migrator_payload.get("wait_for_migrators", [])

        need_to_wait = False
        if wait_for_migrators:
            found_migrators = set()
            for migration in attrs.get("pr_info", {}).get("PRed", []):
                name = migration.get("data", {}).get("name", "")
                if not name or name not in wait_for_migrators:
                    continue
                found_migrators.add(name)
                state = migration.get("PR", {}).get("state", "")
                if state != "closed":
                    need_to_wait = True
            if set(wait_for_migrators) - found_migrators:
                need_to_wait = True

        logger.debug(
            "filter %s: need to wait for %s",
            attrs.get("name", ""),
            wait_for_migrators,
        )

        return need_to_wait or super().filter_node_migrated(attrs, not_bad_str_start)

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> MigrationUidTypedDict | Literal[False]:
        # if conda-forge-pinning update the pins and close the migration
        if attrs.get("name", "") == "conda-forge-pinning":
            # read up the conda build config
            with pushd(recipe_dir), open("conda_build_config.yaml") as f:
                cbc_contents = f.read()
            merged_cbc = merge_migrator_cbc(self.yaml_contents, cbc_contents)
            with pushd(os.path.join(recipe_dir, "migrations")):
                os.remove(f"{self.name}.yaml")
            # replace the conda build config with the merged one
            with pushd(recipe_dir), open("conda_build_config.yaml", "w") as f:
                f.write(merged_cbc)
            # don't need to bump build number once we move to datetime
            # version numbers for pinning
            return super().migrate(recipe_dir, attrs)

        else:
            # in case the render is old
            os.makedirs(os.path.join(recipe_dir, "../.ci_support"), exist_ok=True)
            with pushd(os.path.join(recipe_dir, "../.ci_support")):
                os.makedirs("migrations", exist_ok=True)
                with pushd("migrations"):
                    with open(f"{self.name}.yaml", "w") as f:
                        f.write(self.yaml_contents)

            if self.conda_forge_yml_patches is not None:
                with pushd(os.path.join(recipe_dir, "..")):
                    with open("conda-forge.yml") as fp:
                        cfg = yaml_safe_load(fp.read())
                    _patch_dict(cfg, self.conda_forge_yml_patches)
                    with open("conda-forge.yml", "w") as fp:
                        yaml_safe_dump(cfg, fp)

            with pushd(recipe_dir):
                if os.path.exists("recipe.yaml"):
                    self.set_build_number("recipe.yaml")
                else:
                    self.set_build_number("meta.yaml")

            return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: ClonedFeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        name = self.unique_name
        url = f"https://conda-forge.org/status/migration/?name={name}"
        if feedstock_ctx.feedstock_name == "conda-forge-pinning":
            additional_body = (
                "This PR has been triggered in an effort to close out the "
                "migration for [**{name}**]({url}).\n\n"
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
        else:
            additional_body = (
                "This PR has been triggered in an effort to update "
                "[**{name}**]({url}).\n\n"
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

        commit_body = "\n> ".join(
            self.commit_message(feedstock_ctx).splitlines()[1:],
        )
        if commit_body:
            additional_body += (
                "\n\n"
                "Here are some more details about this specific migrator:\n\n"
                "> {commit_body}\n\n"
                "<hr>"
            ).format(commit_body=commit_body)

        children = "\n".join(
            [" - %s" % ch for ch in self.downstream_children(feedstock_ctx)],
        )
        if len(children) > 0:
            additional_body += (
                "\n\n"
                "This package has the following downstream children:\n"
                "{children}\n"
                "and potentially more.\n\n"
                "<hr>"
            ).format(children=children)

        return body.format(additional_body)

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        if self.name:
            if feedstock_ctx.feedstock_name == "conda-forge-pinning":
                return f"Close out migration for {self.name}"
            default_msg = "Rebuild for " + self.name
        else:
            default_msg = "Bump build number"
        return self.loaded_yaml.get("__migrator", {}).get("commit_message", default_msg)

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        if (
            get_keys_default(
                feedstock_ctx.attrs,
                ["conda-forge.yml", "bot", "automerge"],
                {},
                False,
            )
            in {"migration", True}
        ) and self.automerge:
            add_slug = "[bot-automerge] "
        else:
            add_slug = ""

        title = self.commit_message(feedstock_ctx).splitlines()[0]

        return add_slug + title

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        s_obj = str(self.obj_version) if self.obj_version else ""
        return f"rebuild-{self.name.lower().replace(' ', '_')}-{self.migrator_version}-{s_obj}"  # noqa

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        n = super().migrator_uid(attrs)
        n["name"] = self.name
        return n


def _compute_pin_impact(
    total_graph: nx.DiGraph, package_names: tuple[str], outputs_lut: dict[str, str]
) -> int:
    # Generally, the packages themselves should be excluded from the migration;
    # an example for exceptions are migrations for new python versions
    # where numpy needs to be rebuilt despite being pinned.
    excluded_feedstocks = set()
    for node in package_names:
        excluded_feedstocks.update(outputs_lut.get(node, {node}))

    included_nodes = 0

    for node, node_attrs in total_graph.nodes.items():
        # always keep pinning
        if node == "conda-forge-pinning":
            included_nodes += 1
        else:
            with node_attrs["payload"] as attrs:
                requirements = attrs.get("requirements", {})
                host = requirements.get("host", set())
                build = requirements.get("build", set())
                bh = host or build
                only_python = "python" in package_names
                inclusion_criteria = bh & set(package_names) and (
                    not all_noarch(attrs, only_python=only_python)
                )
                if inclusion_criteria and node not in excluded_feedstocks:
                    included_nodes += 1

    return included_nodes


class MigrationYamlCreator(Migrator):
    """Migrator creating migration yaml files."""

    migrator_version = 0
    rerender = False

    # TODO: add a description kwarg for the status page at some point.
    # TODO: make yaml_contents an arg?
    def __init__(
        self,
        *,
        package_name: str,
        new_pin_version: str,
        current_pin: str,
        pin_spec: str,
        feedstock_name: str,
        total_graph: nx.DiGraph | None = None,
        graph: nx.DiGraph | None = None,
        pin_impact: Optional[int] = None,
        pr_limit: int = 0,
        bump_number: int = 1,
        effective_graph: nx.DiGraph = None,
        pinnings: list[str] | None = None,
        **kwargs: Any,
    ):
        if pinnings is None:
            pinnings = [package_name]

        if pin_impact is None:
            if total_graph is not None:
                outputs_lut = get_outputs_lut(total_graph, graph, effective_graph)
                pin_impact = _compute_pin_impact(
                    total_graph, tuple(pinnings), outputs_lut
                )
            else:
                pin_impact = -1

        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "package_name": package_name,
                "new_pin_version": new_pin_version,
                "current_pin": current_pin,
                "pin_spec": pin_spec,
                "feedstock_name": feedstock_name,
                "graph": graph,
                "pr_limit": pr_limit,
                "bump_number": bump_number,
                "pin_impact": pin_impact,
                "effective_graph": effective_graph,
                "pinnings": pinnings,
                "total_graph": total_graph,
            }
            self._init_kwargs.update(copy.deepcopy(kwargs))

        self.feedstock_name = feedstock_name
        self.pin_spec = pin_spec
        self.current_pin = current_pin
        self.new_pin_version = ".".join(
            new_pin_version.split(".")[: len(pin_spec.split("."))],
        )
        self.package_name = package_name
        self.bump_number = bump_number
        self.name = package_name + " pinning"
        self.pin_impact = pin_impact or -1
        self.pinnings = pinnings

        super().__init__(
            pr_limit=pr_limit,
            graph=graph,
            effective_graph=effective_graph,
            total_graph=total_graph,
        )

    def filter_not_in_migration(self, attrs, not_bad_str_start=""):
        if (
            attrs.get("name", "") == "conda-forge-pinning"
            or attrs.get("feedstock_name", "") == "conda-forge-pinning"
        ):
            return super().filter_not_in_migration(attrs, not_bad_str_start)
        else:
            return True

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> MigrationUidTypedDict | Literal[False]:
        migration_yaml_dict = {
            "__migrator": {
                "build_number": 1,
                "kind": "version",
                "migration_number": 1,
                "commit_message": f"Rebuild for {self.package_name} {self.new_pin_version}",
            },
            "migrator_ts": float(time.time()),
        }
        for pkg in self.pinnings:
            migration_yaml_dict[pkg] = [self.new_pin_version]

        with pushd(os.path.join(recipe_dir, "migrations")):
            mig_fname = "{}{}.yaml".format(
                self.package_name,
                self.new_pin_version.replace(".", ""),
            )
            with open(mig_fname, "w") as f:
                yaml_safe_dump(
                    migration_yaml_dict,
                    f,
                )

        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: ClonedFeedstockContext) -> str:
        body = (
            "This PR has been triggered in an effort to update the pin for"
            " **{name}**. The current pinned version is {current_pin}, "
            "the latest available version is {new_pin_version} and the max "
            "pin pattern is {pin_spec}. This migration will impact {len_graph} "
            "feedstocks.\n\n"
            "Checklist:\n"
            "- [ ] The new version is a stable supported pin. \n"
            "- [ ] I checked that the ABI changed from {current_pin} to "
            "{new_pin_version}. \n"
            "\n"
            "**Please note that if you close this PR we presume that "
            "the new pin has been rejected.\n\n"
            "@conda-forge-admin please ping {feedstock_name}\n"
            "{link}"
            "".format(
                name=self.package_name,
                pin_spec=self.pin_spec,
                current_pin=self.current_pin,
                new_pin_version=self.new_pin_version,
                feedstock_name=self.feedstock_name,
                len_graph=(
                    self.pin_impact if self.pin_impact >= 0 else "an unknown number of"
                ),
                link=f"\n\n<sub>This PR was generated by {get_bot_run_url()} - please use this URL for debugging.</sub>",
            )
        )
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return f"Update pin for {self.package_name}"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return f"Update pin for {self.package_name}"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        s_obj = str(self.obj_version) if self.obj_version else ""
        return (
            f"new_pin-{self.package_name.lower().replace(' ', '_')}-"
            f"{self.new_pin_version}-{self.migrator_version}-{s_obj}"
        )

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        n = super().migrator_uid(attrs)
        n["name"] = self.package_name
        n["pin_version"] = self.new_pin_version
        return n

    def order(
        self,
        graph: nx.DiGraph,
        total_graph: nx.DiGraph,
    ) -> Sequence["PackageName"]:
        """Run the order by number of decedents, ties are resolved by package name."""
        return sorted(
            list(graph.nodes),
            key=lambda x: (len(nx.descendants(total_graph, x)), RNG.random()),
            reverse=True,
        )


def _req_is_python(req):
    return PIN_SEP_PAT.split(req)[0].strip().lower() == "python"


def _combine_build(output_build, global_build):
    build = copy.deepcopy(global_build)
    build.update(output_build)
    return build


def all_noarch(attrs, only_python=False):
    meta_yaml = attrs.get("meta_yaml", {}) or {}
    global_build = meta_yaml.get("build", {}) or {}

    if not only_python:
        outputs = meta_yaml.get("outputs", [])
        if meta_yaml.get("outputs", []):
            return all(
                "noarch" in _combine_build(output.get("build", {}) or {}, global_build)
                for output in outputs
            )

        return "noarch" in global_build
    else:
        reqs = (
            meta_yaml.get("requirements", {}).get("host", [])
            or meta_yaml.get("requirements", {}).get("build", [])
            or []
        )
        if any(_req_is_python(req) for req in reqs):
            all_noarch = "python" == global_build.get("noarch", None)
        else:
            all_noarch = True

        for output in meta_yaml.get("outputs", []):
            # some nodes have None
            _build = _combine_build(output.get("build", {}) or {}, global_build)

            # some nodes have a list here
            _reqs = output.get("requirements", {})
            if not isinstance(_reqs, list):
                _reqs = _reqs.get("host", []) or _reqs.get("build", []) or []

            if any(_req_is_python(req) for req in _reqs):
                _all_noarch = "python" == _build.get("noarch", None)
            else:
                _all_noarch = True

            all_noarch = all_noarch and _all_noarch

    return all_noarch
