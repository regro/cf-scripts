"""Base classes for migrating repos."""

import contextlib
import copy
import logging
import re
import secrets
import typing
from pathlib import Path
from typing import Any, List, Sequence, Set

import networkx as nx
import numpy as np

from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.lazy_json_backends import LazyJson
from conda_forge_tick.update_recipe import update_build_number, v1_recipe
from conda_forge_tick.utils import (
    frozen_to_json_friendly,
    get_bot_run_url,
    get_keys_default,
    get_recipe_schema_version,
    pluck,
)

if typing.TYPE_CHECKING:
    from conda_forge_tick.utils import JsonFriendly

    from ..migrators_types import AttrsTypedDict, MigrationUidTypedDict, PackageName


logger = logging.getLogger(__name__)

RNG = secrets.SystemRandom()


def skip_migrator_due_to_schema(
    attrs: "AttrsTypedDict", allowed_schema_versions: List[int]
) -> bool:
    __name = attrs.get("name", "")
    schema_version = get_recipe_schema_version(attrs)
    if schema_version not in allowed_schema_versions:
        logger.debug(
            "%s: schema version not allowed - %r not in %r",
            __name,
            attrs["meta_yaml"].get("schema_version", 0),
            allowed_schema_versions,
        )
        return True
    else:
        return False


def get_outputs_lut(
    total_graph: nx.DiGraph | None,
    graph: nx.DiGraph | None,
    effective_graph: nx.DiGraph | None,
) -> dict[str, str]:
    outputs_lut = None
    for gx in [total_graph, graph, effective_graph]:
        if gx is not None and "outputs_lut" in gx.graph:
            return gx.graph["outputs_lut"]
    if outputs_lut is None:
        raise ValueError(
            "Either `total_graph` or both `graph` and `effective_graph` "
            "must be provided and must contain `outputs_lut` in their "
            "`.graph` attribute."
        )


@contextlib.contextmanager
def _lazy_json_or_dict(data):
    if isinstance(data, LazyJson):
        with data as _data:
            yield _data
    else:
        yield data


def _make_migrator_graph(graph, migrator, effective=False, pluck_nodes=True):
    """Prune graph only to nodes that need rebuilds."""
    gx2 = copy.deepcopy(graph)

    # Prune graph to only things that need builds right now
    nodes_to_pluck = set()
    for node in list(gx2.nodes):
        if "payload" not in gx2.nodes[node]:
            logger.critical("node %s: no payload, removing", node)
            nodes_to_pluck.add(node)
            continue

        with _lazy_json_or_dict(graph.nodes[node]["payload"]) as attrs:
            had_orig_branch = "branch" in attrs
            orig_branch = attrs.get("branch")
            try:
                base_branches = migrator.get_possible_feedstock_branches(attrs)
                filters = []
                for base_branch in base_branches:
                    attrs["branch"] = base_branch
                    if effective:
                        filters.append(migrator.filter_node_migrated(attrs))
                    else:
                        filters.append(migrator.filter_not_in_migration(attrs))
                if filters and all(filters):
                    nodes_to_pluck.add(node)
            finally:
                if had_orig_branch:
                    attrs["branch"] = orig_branch
                else:
                    del attrs["branch"]

    # the plucking
    for node in nodes_to_pluck:
        if pluck_nodes:
            pluck(gx2, node)
        else:
            gx2.remove_node(node)
    gx2.remove_edges_from(nx.selfloop_edges(gx2))
    return gx2


def _sanitized_muids(pred: List[dict]) -> List["JsonFriendly"]:
    lst = []
    for pr in pred:
        d: "JsonFriendly" = {"data": pr["data"], "keys": pr["keys"]}
        lst.append(d)
    return lst


def _parse_bad_attr(attrs: "AttrsTypedDict", not_bad_str_start: str) -> bool:
    """Overlook some bad entries."""
    bad = attrs.get("pr_info", {}).get("bad", False)
    if isinstance(bad, str):
        bad_bool = not bad.startswith(not_bad_str_start)
    else:
        bad_bool = bad

    return bad_bool or attrs.get("parsing_error", False)


def _gen_active_feedstocks_payloads(nodes, gx):
    for node in nodes:
        try:
            payload = gx.nodes[node]["payload"]
        except KeyError as e:
            print(node)
            raise e

        # we don't need to look at archived feedstocks
        # they are always "migrated"
        if payload.get("archived", False):
            continue
        else:
            yield node, payload


def _migrator_hash(klass, args, kwargs):
    import hashlib

    from conda_forge_tick.lazy_json_backends import dumps

    data = {
        "class": klass,
        "args": args,
        "kwargs": kwargs,
    }

    return hashlib.sha1(dumps(data).encode("utf-8")).hexdigest()


def _make_migrator_lazy_json_name(mgr, data):
    return (
        mgr.name
        if hasattr(mgr, "name")
        else mgr.__class__.__name__
        + (
            ""
            if len(mgr._init_args) == 0 and len(mgr._init_kwargs) == 0
            else "_h"
            + _migrator_hash(
                data["class"],
                data["args"],
                data["kwargs"],
            )
        )
    ).replace(" ", "_")


def make_from_lazy_json_data(data):
    """Deserialize the migrator from LazyJson-compatible data."""
    import conda_forge_tick.migrators

    cls = getattr(conda_forge_tick.migrators, data["class"])

    kwargs = copy.deepcopy(data["kwargs"])
    if (
        "piggy_back_migrations" in kwargs
        and kwargs["piggy_back_migrations"]
        and isinstance(kwargs["piggy_back_migrations"][0], dict)
    ):
        kwargs["piggy_back_migrations"] = [
            make_from_lazy_json_data(mini_migrator)
            for mini_migrator in kwargs["piggy_back_migrations"]
        ]

    return cls(*data["args"], **kwargs)


class MiniMigrator:
    post_migration = False
    allowed_schema_versions = [0]

    def __init__(self):
        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {}

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """If true don't act upon node.

        Parameters
        ----------
        attrs : dict
            The node attributes

        Returns
        -------
        bool :
            True if node is to be skipped
        """
        return skip_migrator_due_to_schema(attrs, self.allowed_schema_versions)

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        """Perform the migration, updating the ``meta.yaml``.

        Parameters
        ----------
        recipe_dir : str
            The directory of the recipe
        attrs : dict
            The node attributes
        """
        return

    def to_lazy_json_data(self):
        """Serialize the migrator to LazyJson-compatible data."""
        data = {
            "__mini_migrator__": True,
            "class": self.__class__.__name__,
            "args": self._init_args,
            "kwargs": self._init_kwargs,
        }
        data["name"] = _make_migrator_lazy_json_name(self, data)
        return data


class Migrator:
    """Base class for Migrators.

    Initialization of Instances
    ---------------------------
    When a migrator is initialized, you need to supply at least the following items

    - pr_limit: The number of PRs the migrator can open in a given run of the bot.
    - total_graph: The entire graph of conda-forge feedstocks.
    """

    name: str

    rerender = True

    max_solver_attempts = 3

    # bump this if the migrator object needs a change mid migration
    migrator_version = 0

    allow_empty_commits = False

    allowed_schema_versions = [0]

    pluck_nodes = True

    build_patterns = (
        (re.compile(r"(\s*?)number:\s*([0-9]+)"), "number: {}"),
        (
            re.compile(r'(\s*?){%\s*set build_number\s*=\s*"?([0-9]+)"?\s*%}'),
            "{{% set build_number = {} %}}",
        ),
        (
            re.compile(r'(\s*?){%\s*set build\s*=\s*"?([0-9]+)"?\s*%}'),
            "{{% set build = {} %}}",
        ),
    )

    def __init__(
        self,
        total_graph: nx.DiGraph | None = None,
        graph: nx.DiGraph | None = None,
        effective_graph: nx.DiGraph | None = None,
        *,
        pr_limit: int = 0,
        # TODO: Validate this?
        obj_version: int | None = None,
        piggy_back_migrations: Sequence[MiniMigrator] | None = None,
        check_solvable: bool = True,
    ):
        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "pr_limit": pr_limit,
                "obj_version": obj_version,
                "piggy_back_migrations": piggy_back_migrations,
                "check_solvable": check_solvable,
            }

        self.piggy_back_migrations = piggy_back_migrations or []
        self._pr_limit = pr_limit
        self.obj_version = obj_version
        self.check_solvable = check_solvable
        self.graph = graph
        self.effective_graph = effective_graph
        self.total_graph = total_graph

        if total_graph is not None:
            if graph is not None or effective_graph is not None:
                raise ValueError(
                    "Cannot pass both `total_graph` and `graph` or "
                    "`effective_graph` to the Migrator."
                )

            graph = _make_migrator_graph(
                total_graph, self, effective=False, pluck_nodes=self.pluck_nodes
            )
            self.graph = graph
            self._init_kwargs["graph"] = graph

            effective_graph = _make_migrator_graph(
                self.graph, self, effective=True, pluck_nodes=self.pluck_nodes
            )
            self.effective_graph = effective_graph
            self._init_kwargs["effective_graph"] = effective_graph

            # do not need this any more
            self._init_kwargs["total_graph"] = None
        else:
            if graph is None or effective_graph is None:
                raise ValueError(
                    "Must pass graph and effective_graph "
                    "to the Migrator if total_graph is not passed."
                )
            self._init_kwargs["graph"] = graph
            self._init_kwargs["effective_graph"] = effective_graph
            self._init_kwargs["total_graph"] = total_graph

    def to_lazy_json_data(self):
        """Serialize the migrator to LazyJson-compatible data."""
        kwargs = copy.deepcopy(self._init_kwargs)
        if (
            "piggy_back_migrations" in kwargs
            and kwargs["piggy_back_migrations"]
            and isinstance(kwargs["piggy_back_migrations"][0], MiniMigrator)
        ):
            kwargs["piggy_back_migrations"] = [
                mini_migrator.to_lazy_json_data()
                for mini_migrator in kwargs["piggy_back_migrations"]
            ]

        data = {
            "__migrator__": True,
            "class": self.__class__.__name__,
            "args": self._init_args,
            "kwargs": kwargs,
        }
        data["name"] = _make_migrator_lazy_json_name(self, data)
        return data

    @property
    def pr_limit(self):
        return self._pr_limit

    @pr_limit.setter
    def pr_limit(self, value):
        self._pr_limit = value
        if hasattr(self, "_init_kwargs"):
            self._init_kwargs["pr_limit"] = value

    def downstream_children(
        self,
        feedstock_ctx: FeedstockContext,
        limit: int = 5,
    ) -> List["PackageName"]:
        """Get a list of follow on packages."""
        return [
            a[1]
            for a in list(
                self.effective_graph.out_edges(feedstock_ctx.feedstock_name),
            )
        ][:limit]

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """If True don't act upon a node.

        Parameters
        ----------
        attrs : dict
            The node attributes
        not_bad_str_start : str, optional
            If the 'bad' notice starts with the string then it is not
            to be excluded. For example, rebuild migrations don't need
            to worry about if the upstream can be fetched. Defaults to ``''``

        Returns
        -------
        bool :
            True if node is to be skipped
        """
        return self.filter_not_in_migration(
            attrs, not_bad_str_start
        ) or self.filter_node_migrated(attrs, not_bad_str_start)

    def filter_not_in_migration(
        self, attrs: "AttrsTypedDict", not_bad_str_start: str = ""
    ) -> bool:
        """If true don't act upon node because it is not in the migration."""
        # never run on archived feedstocks
        # don't run on bad nodes

        __name = attrs.get("name", "")

        if attrs.get("archived", False):
            logger.debug("%s: archived", __name)

        bad_attr = _parse_bad_attr(attrs, not_bad_str_start)
        if bad_attr:
            logger.debug("%s: bad attr - %s", __name, bad_attr)

        return (
            attrs.get("archived", False)
            or bad_attr
            or skip_migrator_due_to_schema(attrs, self.allowed_schema_versions)
        )

    def filter_node_migrated(
        self, attrs: "AttrsTypedDict", not_bad_str_start: str = ""
    ) -> bool:
        """If true don't act upon node because it is already migrated."""
        # don't run on things we've already done

        __name = attrs.get("name", "")

        pr_data = frozen_to_json_friendly(self.migrator_uid(attrs))
        migrator_uid: "MigrationUidTypedDict" = typing.cast(
            "MigrationUidTypedDict",
            pr_data["data"],
        )
        already_migrated_uids: typing.Iterable["MigrationUidTypedDict"] = list(
            z["data"] for z in attrs.get("pr_info", {}).get("PRed", [])
        )
        already_pred = migrator_uid in already_migrated_uids
        if already_pred:
            ind = already_migrated_uids.index(migrator_uid)
            logger.debug("%s: already PRed: uid: %s", __name, migrator_uid)
            if "PR" in attrs.get("pr_info", {}).get("PRed", [])[ind]:
                if isinstance(
                    attrs.get("pr_info", {}).get("PRed", [])[ind]["PR"],
                    LazyJson,
                ):
                    with attrs.get("pr_info", {}).get("PRed", [])[ind][
                        "PR"
                    ] as mg_attrs:
                        logger.debug(
                            "%s: already PRed: PR file: %s", __name, mg_attrs.file_name
                        )

                        html_url = mg_attrs.get("html_url", "no url")

                        logger.debug("%s: already PRed: url: %s", __name, html_url)

        return already_pred

    def get_possible_feedstock_branches(self, attrs: "AttrsTypedDict") -> List[str]:
        """Return the valid possible branches to which to apply this migration to
        for the given attrs.

        Parameters
        ----------
        attrs : dict
            The node attributes

        Returns
        -------
        branches : list of str
            List if valid branches for this migration.
        """
        branches = ["main"]
        try:
            branches += get_keys_default(
                attrs,
                ["conda-forge.yml", "bot", "abi_migration_branches"],
                {},
                [],
            )
        except Exception:
            logger.exception("Invalid value for %r", attrs.get("conda-forge.yml", {}))
        # make sure this is always a string
        return [str(b) for b in branches]

    def run_pre_piggyback_migrations(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        """Perform any pre piggyback migrations, updating the feedstock.

        Parameters
        ----------
        recipe_dir : str
            The directory of the recipe
        attrs : dict
            The node attributes

        """
        for mini_migrator in self.piggy_back_migrations:
            if mini_migrator.post_migration:
                continue
            if not mini_migrator.filter(attrs):
                mini_migrator.migrate(recipe_dir, attrs, **kwargs)

    def run_post_piggyback_migrations(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        """Perform any post piggyback migrations, updating the feedstock.

        Parameters
        ----------
        recipe_dir : str
            The directory of the recipe
        attrs : dict
            The node attributes

        """
        for mini_migrator in self.piggy_back_migrations:
            if not mini_migrator.post_migration:
                continue
            if not mini_migrator.filter(attrs):
                mini_migrator.migrate(recipe_dir, attrs, **kwargs)

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        """Perform the migration, updating the ``meta.yaml``.

        Parameters
        ----------
        recipe_dir : str
            The directory of the recipe
        attrs : dict
            The node attributes

        Returns
        -------
        namedtuple or bool:
            If namedtuple continue with PR, if False scrap local folder
        """
        return self.migrator_uid(attrs)

    def pr_body(
        self, feedstock_ctx: ClonedFeedstockContext, add_label_text=True
    ) -> str:
        """Create a PR message body.

        Returns
        -------
        body
            The body of the PR message
        feedstock_ctx
            The current ClonedFeedstockContext.
        """
        body = "{}\n\n"

        if add_label_text:
            body += (
                "If this PR was opened in error or needs to be updated please add "
                "the `bot-rerun` label to this PR. The bot will close this PR and "
                "schedule another one. If you do not have permissions to add this "
                "label, you can use the phrase "
                "<code>@<space/>conda-forge-admin, please rerun bot</code> "
                "in a PR comment to have the `conda-forge-admin` add it for you.\n\n"
            )

        body += (
            "<sub>"
            "This PR was created by the [regro-cf-autotick-bot](https://github.com/regro/cf-scripts). "
            "The **regro-cf-autotick-bot** is a service to automatically "
            "track the dependency graph, migrate packages, and "
            "propose package version updates for conda-forge. "
            "Feel free to drop us a line if there are any "
            "[issues](https://github.com/regro/cf-scripts/issues)! "
            + f"This PR was generated by {get_bot_run_url()} - please use this URL for debugging."
            + "</sub>"
        )
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        """Create a commit message."""
        return f"migration: {self.__class__.__name__}"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        """Get the PR title."""
        return "PR from Regro-cf-autotick-bot"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        """Get branch to use on local and remote."""
        return "bot-pr"

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        """Make a unique id for this migrator and node attrs.

        Parameters
        ----------
        attrs
            Node attrs

        Returns
        -------
        nt: frozen_to_json_friendly
            The unique id as a frozen_to_json_friendly (so it can be
            used as keys in dicts)
        """
        d: "MigrationUidTypedDict" = {
            "migrator_name": self.__class__.__name__,
            "migrator_version": self.migrator_version,
            "bot_rerun": False,
        }
        # Carveout for old migrators w/o obj_versions
        if self.obj_version:
            d["migrator_object_version"] = self.obj_version

        branch = attrs.get("branch", "main")
        if branch != "main" and branch != "master":
            d["branch"] = branch

        return d

    def order(
        self,
        graph: nx.DiGraph,
        total_graph: nx.DiGraph,
    ) -> Sequence["PackageName"]:
        """Determine migration order.

        The feedstocks are reverse sorted by

            - number of decedents if not a failed migration and not a leaf node
            - a random number in [0, 1] if not failed and a leaf node
            - a random number in [0, val] if failed

        where val is

            min((1.0 + log10(num descendents + 1)) * 0.5, 1.0)

        This formula has the effect of

            - deprioritizing failed nodes by an overall amount (0.5 means there is a
              ~33% percent chance a failed node appears ahead of a non-failed node)
            - boosting failed migrators by a bit if they have a lot of descendents
            - never letting any failed node get ahead of non-failed, non-leaf nodes

        Ties are sorted randomly.
        """
        if hasattr(self, "name"):
            assert isinstance(self.name, str)
            migrator_name = self.name.lower().replace(" ", "")
        else:
            migrator_name = self.__class__.__name__.lower()

        def _not_has_error_func(node):
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
                    self.max_solver_attempts,
                )
                >= self.max_solver_attempts
            ):
                return 0
            else:
                return 1

        _not_has_error = {node: _not_has_error_func(node) for node in list(graph.nodes)}
        boost = {
            node: 1.0 + np.log10(len(nx.descendants(total_graph, node)) + 1)
            for node in list(graph.nodes)
        }

        return sorted(
            list(graph.nodes),
            key=lambda x: (
                (
                    RNG.random()
                    * (1.0 if _not_has_error[x] else min(boost[x] * 0.5, 1.0))
                    if (
                        (not _not_has_error[x])
                        or len(nx.descendants(total_graph, x)) == 0
                    )
                    else len(nx.descendants(total_graph, x))
                ),
                RNG.random(),
            ),
            reverse=True,
        )

    def set_build_number(self, filename: str | Path) -> None:
        """Bump the build number of the specified recipe.

        Parameters
        ----------
        filename : str
            Path the the meta.yaml
        """
        filename = Path(filename)
        if filename.name == "recipe.yaml":
            filename.write_text(
                v1_recipe.update_build_number(filename, self.new_build_number)
            )
        else:
            raw = filename.read_text()

            new_myaml = update_build_number(
                raw,
                self.new_build_number,
                build_patterns=self.build_patterns,
            )

            filename.write_text(new_myaml)

    def new_build_number(self, old_number: int) -> int:
        """Determine the new build number to use.

        Parameters
        ----------
        old_number : int
            Old build number detected

        Returns
        -------
        new_build_number
        """
        increment = getattr(self, "bump_number", 1)
        return old_number + increment

    @classmethod
    def migrator_label(cls) -> dict:
        # This is the label that the bot will attach to a pr made by the bot
        return {
            "name": f"bot-{cls.__name__.lower()}",
            "description": (cls.__doc__ or "").strip(),
            "color": "#6c64ff",
        }


class GraphMigrator(Migrator):
    def __init__(
        self,
        *,
        total_graph: nx.DiGraph | None = None,
        name: str | None = None,
        graph: nx.DiGraph | None = None,
        pr_limit: int = 0,
        top_level: Set["PackageName"] | None = None,
        cycles: Sequence["PackageName"] | None = None,
        obj_version: int | None = None,
        piggy_back_migrations: Sequence[MiniMigrator] | None = None,
        check_solvable: bool = True,
        ignored_deps_per_node=None,
        effective_graph: nx.DiGraph | None = None,
    ):
        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "name": name,
                "graph": graph,
                "pr_limit": pr_limit,
                "top_level": top_level,
                "cycles": cycles,
                "obj_version": obj_version,
                "piggy_back_migrations": piggy_back_migrations,
                "check_solvable": check_solvable,
                "ignored_deps_per_node": ignored_deps_per_node,
                "effective_graph": effective_graph,
                "total_graph": total_graph,
            }

        self.name = name
        self.top_level = top_level or set()
        self.cycles = set(cycles or [])
        self.ignored_deps_per_node = ignored_deps_per_node or {}

        super().__init__(
            pr_limit=pr_limit,
            obj_version=obj_version,
            piggy_back_migrations=piggy_back_migrations,
            check_solvable=check_solvable,
            graph=graph,
            effective_graph=effective_graph,
            total_graph=total_graph,
        )

    def all_predecessors_issued(self, attrs: "AttrsTypedDict") -> bool:
        # Check if all upstreams have been issue and are stale
        for node, payload in _gen_active_feedstocks_payloads(
            self.graph.predecessors(attrs["feedstock_name"]),
            self.graph,
        ):
            if node in self.ignored_deps_per_node.get(
                attrs.get("feedstock_name", None),
                [],
            ):
                continue

            muid = frozen_to_json_friendly(self.migrator_uid(payload))
            pr_muids = _sanitized_muids(payload.get("pr_info", {}).get("PRed", []))
            if muid not in pr_muids:
                logger.debug(
                    "node %s PR %s not yet issued!",
                    node,
                    muid.get("data", {}).get("name", None),
                )
                # not yet issued
                return False

        return True

    def predecessors_not_yet_built(self, attrs: "AttrsTypedDict") -> bool:
        # Check if all upstreams have been built
        for node, payload in _gen_active_feedstocks_payloads(
            self.graph.predecessors(attrs["feedstock_name"]),
            self.graph,
        ):
            if node in self.ignored_deps_per_node.get(
                attrs.get("feedstock_name", None),
                [],
            ):
                continue

            muid = frozen_to_json_friendly(self.migrator_uid(payload))

            if muid not in _sanitized_muids(
                payload.get("pr_info", {}).get("PRed", []),
            ):
                logger.debug("not yet built: %s", node)
                return True

            # This is due to some PRed_json loss due to bad graph deploy outage
            for m_pred_json in payload.get("pr_info", {}).get("PRed", []):
                if m_pred_json["data"] == muid["data"]:
                    break
            else:
                m_pred_json = None

            # note that if the bot is missing the PR we assume it is open
            # so that errors halt the migration and can be fixed
            if (
                m_pred_json
                and m_pred_json.get("PR", {"state": "open"}).get("state", "") == "open"
            ):
                logger.debug("not yet built: %s", node)
                return True

        return False

    def filter_not_in_migration(self, attrs, not_bad_str_start=""):
        if super().filter_not_in_migration(attrs, not_bad_str_start):
            return True

        name = attrs.get("name", "")
        _gx = self.total_graph or self.graph
        not_in_migration = attrs.get("feedstock_name", None) not in _gx

        if not_in_migration:
            logger.debug("filter %s: node not in graph", name)

        return not_in_migration

    def filter_node_migrated(self, attrs, not_bad_str_start=""):
        name = attrs.get("name", "")

        # If in top level or in a cycle don't check for upstreams just build
        is_top_level = (attrs["feedstock_name"] in self.top_level) or (
            attrs["feedstock_name"] in self.cycles
        )
        if is_top_level:
            logger.debug("not filtered %s: top level", name)
            node_is_ready = True
        else:
            if name == "conda-forge-pinning":
                if self.all_predecessors_issued(attrs=attrs):
                    node_is_ready = True
                else:
                    logger.debug("filtered %s: pinning parents not issued", name)
                    node_is_ready = False
            else:
                # Check if all upstreams have been built
                if self.predecessors_not_yet_built(attrs=attrs):
                    logger.debug("filter %s: parents not built", name)
                    node_is_ready = False
                else:
                    node_is_ready = True

        return (not node_is_ready) or super().filter_node_migrated(attrs, "Upstream:")

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        n = super().migrator_uid(attrs)
        n["name"] = self.name
        return n
