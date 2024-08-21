import copy
import logging
import os
import random
import re
import time
import typing
from collections import defaultdict
from typing import Any, List, MutableSet, Optional, Sequence, Set

import networkx as nx

from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.feedstock_parser import PIN_SEP_PAT
from conda_forge_tick.make_graph import get_deps_from_outputs_lut
from conda_forge_tick.migrators.core import GraphMigrator, Migrator, MiniMigrator
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import (
    get_bot_run_url,
    get_keys_default,
    pluck,
    yaml_safe_dump,
    yaml_safe_load,
)

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict, MigrationUidTypedDict, PackageName

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
    """Merge a migrator_yaml with the conda_build_config_yaml"""
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


class MigrationYaml(GraphMigrator):
    """Migrator for bumping the build number."""

    migrator_version = 0
    rerender = True

    # TODO: add a description kwarg for the status page at some point.
    # TODO: make yaml_contents an arg?
    def __init__(
        self,
        yaml_contents: str,
        name: str,
        graph: nx.DiGraph = None,
        pr_limit: int = 50,
        top_level: Set["PackageName"] = None,
        cycles: Optional[Sequence["PackageName"]] = None,
        migration_number: Optional[int] = None,
        bump_number: int = 1,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
        automerge: bool = False,
        check_solvable=True,
        conda_forge_yml_patches=None,
        ignored_deps_per_node=None,
        max_solver_attempts=3,
        effective_graph: nx.DiGraph = None,
        force_pr_after_solver_attempts=100,
        longterm=False,
        paused=False,
        **kwargs: Any,
    ):
        if not hasattr(self, "_init_args"):
            self._init_args = [yaml_contents, name]

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
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
                "max_solver_attempts": max_solver_attempts,
                "effective_graph": effective_graph,
                "longterm": longterm,
                "force_pr_after_solver_attempts": force_pr_after_solver_attempts,
                "paused": paused,
            }
            self._init_kwargs.update(copy.deepcopy(kwargs))

        super().__init__(
            graph=graph,
            pr_limit=pr_limit,
            obj_version=migration_number,
            piggy_back_migrations=piggy_back_migrations,
            check_solvable=check_solvable,
            ignored_deps_per_node=ignored_deps_per_node,
            effective_graph=effective_graph,
        )
        self.yaml_contents = yaml_contents
        assert isinstance(name, str)
        self.name = name
        self.top_level = top_level or set()
        self.cycles = set(cycles or [])
        self.automerge = automerge
        self.conda_forge_yml_patches = conda_forge_yml_patches
        self.loaded_yaml = yaml_safe_load(self.yaml_contents)
        self.bump_number = bump_number
        self.max_solver_attempts = max_solver_attempts
        self.longterm = longterm
        self.force_pr_after_solver_attempts = force_pr_after_solver_attempts
        self.paused = paused

        self._reset_effective_graph()

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """
        Determine whether migrator needs to be filtered out.

        Return value of True means to skip migrator, False means to go ahead.
        Calls up the MRO until Migrator.filter, see docstring there (./core.py).
        """
        migrator_payload = self.loaded_yaml.get("__migrator", {})
        platform_allowlist = migrator_payload.get("platform_allowlist", [])
        wait_for_migrators = migrator_payload.get("wait_for_migrators", [])

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

        return (
            platform_filtered
            or need_to_wait
            or super().filter(
                attrs=attrs,
                not_bad_str_start=not_bad_str_start,
            )
        )

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
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
                self.set_build_number("meta.yaml")

            return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: ClonedFeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        if feedstock_ctx.feedstock_name == "conda-forge-pinning":
            additional_body = (
                "This PR has been triggered in an effort to close out the "
                "migration for **{name}**.\n\n"
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
                    name=self.name,
                )
            )
        else:
            additional_body = (
                "This PR has been triggered in an effort to update **{name}**.\n\n"
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
                    name=self.name,
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

    def order(
        self,
        graph: nx.DiGraph,
        total_graph: nx.DiGraph,
    ) -> Sequence["PackageName"]:
        """Run the order by number of decedents, ties are resolved by package name"""

        if hasattr(self, "name"):
            assert isinstance(self.name, str)
            migrator_name = self.name.lower().replace(" ", "")
        else:
            migrator_name = self.__class__.__name__.lower()

        def _not_has_error(node):
            if migrator_name in total_graph.nodes[node]["payload"].get(
                "pr_info",
                {},
            ).get("pre_pr_migrator_status", {}) and (
                total_graph.nodes[node]["payload"]
                .get("pr_info", {})
                .get(
                    "pre_pr_migrator_attempts",
                    {},
                )
                .get(
                    migrator_name,
                    3,
                )
                >= self.max_solver_attempts
            ):
                return 0
            else:
                return 1

        return sorted(
            graph,
            key=lambda x: (
                _not_has_error(x),
                (
                    random.uniform(0, 1)
                    if not _not_has_error(x)
                    else len(nx.descendants(total_graph, x))
                ),
                x,
            ),
            reverse=True,
        )


class MigrationYamlCreator(Migrator):
    """Migrator creating migration yaml files."""

    migrator_version = 0
    rerender = False

    # TODO: add a description kwarg for the status page at some point.
    # TODO: make yaml_contents an arg?
    def __init__(
        self,
        package_name: str,
        new_pin_version: str,
        current_pin: str,
        pin_spec: str,
        feedstock_name: str,
        graph: nx.DiGraph,
        pin_impact: Optional[int] = None,
        full_graph: Optional[nx.DiGraph] = None,
        pr_limit: int = 1,
        bump_number: int = 1,
        effective_graph: nx.DiGraph = None,
        pinnings: Optional[List[int]] = None,
        **kwargs: Any,
    ):
        if pinnings is None:
            pinnings = [package_name]

        if pin_impact is None:
            if full_graph is not None:
                pin_impact = len(create_rebuild_graph(full_graph, tuple(pinnings)))
                full_graph = None
            else:
                pin_impact = -1

        if not hasattr(self, "_init_args"):
            self._init_args = [
                package_name,
                new_pin_version,
                current_pin,
                pin_spec,
                feedstock_name,
                graph,
            ]

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "pr_limit": pr_limit,
                "bump_number": bump_number,
                "pin_impact": pin_impact,
                "full_graph": full_graph,
                "effective_graph": effective_graph,
                "pinnings": pinnings,
            }
            self._init_kwargs.update(copy.deepcopy(kwargs))

        super().__init__(
            pr_limit=pr_limit, graph=graph, effective_graph=effective_graph
        )
        self.feedstock_name = feedstock_name
        self.pin_spec = pin_spec
        self.current_pin = current_pin
        self.new_pin_version = ".".join(
            new_pin_version.split(".")[: len(pin_spec.split("."))],
        )
        self.package_name = package_name
        self.bump_number = bump_number
        self.name = package_name + " pinning"
        self.pin_impact = pin_impact
        self.pinnings = pinnings

        self._reset_effective_graph()

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        if (
            not super().filter(attrs, not_bad_str_start)
            and attrs.get("name", "") == "conda-forge-pinning"
        ):
            return False
        return True

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
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
                link=f"This PR was generated by {get_bot_run_url()} - please use this URL for debugging.",
            )
        )  # noqa
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
        """Run the order by number of decedents, ties are resolved by package name"""
        return sorted(
            graph,
            key=lambda x: (len(nx.descendants(total_graph, x)), x),
            reverse=True,
        )


def _req_is_python(req):
    return PIN_SEP_PAT.split(req)[0].strip().lower() == "python"


def all_noarch(attrs, only_python=False):
    meta_yaml = attrs.get("meta_yaml", {}) or {}

    if not only_python:
        outputs = meta_yaml.get("outputs", [])
        if meta_yaml.get("outputs", []):
            return all(
                "noarch" in (output.get("build", {}) or {}) for output in outputs
            )

        return "noarch" in (meta_yaml.get("build", {}) or {})

    else:
        reqs = (
            meta_yaml.get("requirements", {}).get("host", [])
            or meta_yaml.get("requirements", {}).get("build", [])
            or []
        )
        if any(_req_is_python(req) for req in reqs):
            all_noarch = "python" == meta_yaml.get("build", {}).get("noarch", None)
        else:
            all_noarch = True

        for output in meta_yaml.get("outputs", []):
            # some nodes have None
            _build = output.get("build", {}) or {}

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


def create_rebuild_graph(
    gx: nx.DiGraph,
    package_names: Sequence[str],
    excluded_feedstocks: MutableSet[str] = None,
    exclude_pinned_pkgs: bool = True,
    include_noarch: bool = False,
) -> nx.DiGraph:
    total_graph = copy.deepcopy(gx)
    excluded_feedstocks = set() if excluded_feedstocks is None else excluded_feedstocks
    # Generally, the packages themselves should be excluded from the migration;
    # an example for exceptions are migrations for new python versions
    # where numpy needs to be rebuilt despite being pinned.
    if exclude_pinned_pkgs:
        for node in package_names:
            excluded_feedstocks.update(gx.graph["outputs_lut"].get(node, {node}))

    included_nodes = set()

    for node, node_attrs in gx.nodes.items():
        # always keep pinning
        if node == "conda-forge-pinning":
            continue
        attrs: "AttrsTypedDict" = node_attrs["payload"]
        requirements = attrs.get("requirements", {})
        host = requirements.get("host", set())
        build = requirements.get("build", set())
        bh = host or build
        only_python = "python" in package_names
        inclusion_criteria = bh & set(package_names) and (
            include_noarch or not all_noarch(attrs, only_python=only_python)
        )
        # get host/build, run and test and launder them through outputs
        # this should fix outputs related issues (eg gdal)
        all_reqs = requirements.get("run", set())
        if inclusion_criteria:
            all_reqs = all_reqs | requirements.get("test", set())
            all_reqs = all_reqs | (host or build)
        rq = get_deps_from_outputs_lut(
            all_reqs,
            gx.graph["outputs_lut"],
        )

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if inclusion_criteria:
            included_nodes.add(node)

    # all nodes have the conda-forge-pinning as child package
    total_graph.add_edges_from([(n, "conda-forge-pinning") for n in total_graph.nodes])
    included_nodes.add("conda-forge-pinning")  # it does not get added above

    # finally remove all nodes that should not be built from the graph
    for node in list(total_graph.nodes):
        # if there isn't a strict dependency or if the feedstock is excluded,
        # remove it while retaining the edges to its parents and children
        if (node not in included_nodes) or (node in excluded_feedstocks):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))
    return total_graph
