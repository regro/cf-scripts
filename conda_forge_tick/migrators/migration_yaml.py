import copy
import os
from itertools import chain
import typing
from typing import Optional, Set, Sequence, Any, MutableSet
import time
import re
from collections import defaultdict
import logging

import networkx as nx
import ruamel.yaml as yaml

from conda_forge_tick.contexts import FeedstockContext
from conda_forge_tick.migrators.core import GraphMigrator, MiniMigrator, Migrator
from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.utils import eval_cmd
from ..utils import pluck

if typing.TYPE_CHECKING:
    from ..migrators_types import (
        MigrationUidTypedDict,
        AttrsTypedDict,
    )

logger = logging.getLogger("conda_forge_tick.migrators.migration_yaml")


def _patch_dict(cfg, patches):
    """Patch a dictionary using a set of patches.

    Given a dict like

        {"a": 10, "b": {"c": 15}}

    a patch like this

        {"a": [11, 12], "b.c": 20}

    will produce

        {"a": [11, 12], "b": {"c": 20}}

    Note that whole keys are replaced wheras keys separated by periods
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
        graph: nx.DiGraph = None,
        name: Optional[str] = None,
        pr_limit: int = 50,
        top_level: Set["PackageName"] = None,
        cycles: Optional[Sequence["PackageName"]] = None,
        migration_number: Optional[int] = None,
        bump_number: int = 1,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
        automerge: bool = False,
        check_solvable=True,
        conda_forge_yml_patches=None,
        **kwargs: Any,
    ):
        super().__init__(
            graph=graph,
            pr_limit=pr_limit,
            obj_version=migration_number,
            piggy_back_migrations=piggy_back_migrations,
            check_solvable=check_solvable,
        )
        self.yaml_contents = yaml_contents
        assert isinstance(name, str)
        self.name: str = name
        self.top_level = top_level or set()
        self.cycles = set(chain.from_iterable(cycles or []))
        self.automerge = automerge
        self.conda_forge_yml_patches = conda_forge_yml_patches

        # auto set the pr_limit for initial things
        number_pred = len(
            [
                k
                for k, v in self.graph.nodes.items()
                if self.migrator_uid(v.get("payload", {}))
                in [vv.get("data", {}) for vv in v.get("payload", {}).get("PRed", [])]
            ],
        )
        if number_pred == 0:
            self.pr_limit = 2
        elif number_pred < 7:
            self.pr_limit = 5
        self.bump_number = bump_number
        print(self.yaml_contents)

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        # if conda-forge-pinning update the pins and close the migration
        if attrs.get("name", "") == "conda-forge-pinning":
            # read up the conda build config
            with indir(recipe_dir), open("conda_build_config.yaml") as f:
                cbc_contents = f.read()
            merged_cbc = merge_migrator_cbc(self.yaml_contents, cbc_contents)
            with indir(os.path.join(recipe_dir, "migrations")):
                os.remove(f"{self.name}.yaml")
            # replace the conda build config with the merged one
            with indir(recipe_dir), open("conda_build_config.yaml", "w") as f:
                f.write(merged_cbc)
            # don't need to bump build number once we move to datetime
            # version numbers for pinning
            return super().migrate(recipe_dir, attrs)

        else:
            # in case the render is old
            os.makedirs(os.path.join(recipe_dir, "../.ci_support"), exist_ok=True)
            with indir(os.path.join(recipe_dir, "../.ci_support")):
                os.makedirs("migrations", exist_ok=True)
                with indir("migrations"):
                    with open(f"{self.name}.yaml", "w") as f:
                        f.write(self.yaml_contents)
                    eval_cmd("git add .")

            if self.conda_forge_yml_patches is not None:
                with indir(os.path.join(recipe_dir, "..")):
                    with open("conda-forge.yml", "r") as fp:
                        cfg = yaml.safe_load(fp.read())
                    _patch_dict(cfg, self.conda_forge_yml_patches)
                    with open("conda-forge.yml", "w") as fp:
                        yaml.dump(cfg, fp, default_flow_style=False, indent=2)
                    eval_cmd("git add conda-forge.yml")

            with indir(recipe_dir):
                self.set_build_number("meta.yaml")

            return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: "FeedstockContext") -> str:
        body = super().pr_body(feedstock_ctx)
        if feedstock_ctx.package_name == "conda-forge-pinning":
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
                "This package has the following downstream children:\n"
                "{children}\n"
                "And potentially more."
                "".format(
                    name=self.name,
                    children="\n".join(self.downstream_children(feedstock_ctx)),
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
                "This package has the following downstream children:\n"
                "{children}\n"
                "And potentially more."
                "".format(
                    name=self.name,
                    children="\n".join(self.downstream_children(feedstock_ctx)),
                )
            )
        body = body.format(additional_body)
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        if self.name:
            if feedstock_ctx.package_name == "conda-forge-pinning":
                return f"Close out migration for {self.name}"
            return "Rebuild for " + self.name
        else:
            return "Bump build number"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        if (
            (
                feedstock_ctx.attrs.get("conda-forge.yml", {})
                .get("bot", {})
                .get("automerge", False)
            )
            and self.automerge
        ):
            add_slug = "[bot-automerge] "
        else:
            add_slug = ""

        if self.name:
            if feedstock_ctx.package_name == "conda-forge-pinning":
                # we never automerge on pinnings
                return f"Close out migration for {self.name}"
            return add_slug + "Rebuild for " + self.name
        else:
            return add_slug + "Bump build number"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        s_obj = str(self.obj_version) if self.obj_version else ""
        return f"rebuild-{self.name.lower().replace(' ', '_')}-{self.migrator_version}-{s_obj}"  # noqa

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        n = super().migrator_uid(attrs)
        n["name"] = self.name
        return n

    def order(
        self, graph: nx.DiGraph, total_graph: nx.DiGraph,
    ) -> Sequence["PackageName"]:
        """Run the order by number of decendents, ties are resolved by package name"""
        return sorted(
            graph, key=lambda x: (len(nx.descendants(total_graph, x)), x), reverse=True,
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
        pr_limit: int = 1,
        bump_number: int = 1,
        **kwargs: Any,
    ):
        super().__init__(pr_limit=pr_limit,)
        self.feedstock_name = feedstock_name
        self.pin_spec = pin_spec
        self.current_pin = current_pin
        self.new_pin_version = (
            '.'.join(new_pin_version.split('.')[:len(pin_spec.split("."))]))
        self.package_name = package_name
        self.bump_number = bump_number
        self.name = package_name + " pinning"
        self.graph = graph

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
            "__migrator": {"build_number": 1, "kind": "version", "migration_number": 1},
            self.package_name: [self.new_pin_version],
            "migrator_ts": float(time.time()),
        }
        with indir(os.path.join(recipe_dir, "migrations")):
            mig_fname = "%s%s.yaml" % (
                self.package_name,
                self.new_pin_version.replace(".", ""),
            )
            with open(mig_fname, "w") as f:
                yaml.dump(migration_yaml_dict, f, default_flow_style=False, indent=2)
            eval_cmd("git add .")

        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: "FeedstockContext") -> str:
        body = super().pr_body(feedstock_ctx)
        additional_body = (
            "This PR has been triggered in an effort to update the pin for"
            " **{name}**. The current pinned version is {current_pin}, "
            "the latest available version is {new_pin_version} and the max "
            "pin pattern is {pin_spec}. This migration will impact {len_graph} "
            "feedstocks.\n\n"
            "Notes and instructions for merging this PR:\n"
            "1. Please merge the PR only if this new version is to be a "
            "supported pin. \n"
            "2. Feel free to push to the bot's branch to update this PR if "
            "needed. \n"
            "3. Please make sure to properly bump the version and build number "
            "of the pinnings package. \n"
            "\n"
            "**Please note that if you close this PR we presume that "
            "the new pin has been rejected.\n\n"
            "@conda-forge-admin please ping {feedstock_name}"
            "".format(
                name=self.package_name,
                pin_spec=self.pin_spec,
                current_pin=self.current_pin,
                new_pin_version=self.new_pin_version,
                feedstock_name=self.feedstock_name,
                len_graph=len(create_rebuild_graph(self.graph, (self.package_name, )))
            )
        )  # noqa
        body = body.format(additional_body)
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
        self, graph: nx.DiGraph, total_graph: nx.DiGraph,
    ) -> Sequence["PackageName"]:
        """Run the order by number of decendents, ties are resolved by package name"""
        return sorted(
            graph, key=lambda x: (len(nx.descendants(total_graph, x)), x), reverse=True,
        )


def create_rebuild_graph(
    gx: nx.DiGraph,
    package_names: Sequence[str],
    excluded_feedstocks: MutableSet[str] = None,
    include_noarch: bool = False
) -> nx.DiGraph:
    total_graph = copy.deepcopy(gx)
    excluded_feedstocks = set() if excluded_feedstocks is None else excluded_feedstocks

    for node, node_attrs in gx.nodes.items():
        # always keep pinning
        if node == 'conda-forge-pinning':
            continue
        attrs: "AttrsTypedDict" = node_attrs["payload"]
        requirements = attrs.get("requirements", {})
        host = requirements.get("host", set())
        build = requirements.get("build", set())
        bh = host or build
        inclusion_criteria = bh & set(package_names) and (
                include_noarch or ("noarch" not in attrs.get("meta_yaml", {}).get("build", {}))
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
        # if there isn't a strict dependency or if the feedstock is excluded,
        # remove it while retaining the edges to its parents and children
        if not inclusion_criteria or node in excluded_feedstocks:
            pluck(total_graph, node)

    # all nodes have the conda-forge-pinning as child package
    total_graph.add_edges_from([(n, 'conda-forge-pinning') for n in total_graph.nodes])

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))
    return total_graph
