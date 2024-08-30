"""Base classes for migrating repos"""

import copy
import datetime
import logging
import re
import typing
from typing import Any, List, Sequence, Set

import dateutil.parser
import networkx as nx

from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.lazy_json_backends import LazyJson
from conda_forge_tick.make_graph import make_outputs_lut_from_graph
from conda_forge_tick.path_lengths import cyclic_topological_sort
from conda_forge_tick.update_recipe import update_build_number
from conda_forge_tick.utils import (
    frozen_to_json_friendly,
    get_bot_run_url,
    get_keys_default,
)

if typing.TYPE_CHECKING:
    from conda_forge_tick.utils import JsonFriendly

    from ..migrators_types import AttrsTypedDict, MigrationUidTypedDict, PackageName


logger = logging.getLogger(__name__)


def _make_effective_graph(graph, migrator):
    """Prune graph only to nodes that need rebuilds."""
    gx2 = copy.deepcopy(graph)

    # Prune graph to only things that need builds right now
    for node in list(gx2.nodes):
        if isinstance(graph.nodes[node]["payload"], LazyJson):
            with graph.nodes[node]["payload"] as _attrs:
                attrs = copy.deepcopy(_attrs.data)
        else:
            attrs = copy.deepcopy(graph.nodes[node]["payload"])
        base_branches = migrator.get_possible_feedstock_branches(attrs)
        filters = []
        for base_branch in base_branches:
            attrs["branch"] = base_branch
            filters.append(migrator.filter(attrs))

        if filters and all(filters):
            gx2.remove_node(node)

    return gx2


def _sanitized_muids(pred: List[dict]) -> List["JsonFriendly"]:
    lst = []
    for pr in pred:
        d: "JsonFriendly" = {"data": pr["data"], "keys": pr["keys"]}
        lst.append(d)
    return lst


def _parse_bad_attr(attrs: "AttrsTypedDict", not_bad_str_start: str) -> bool:
    """Overlook some bad entries"""
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


def _migratror_hash(klass, args, kwargs):
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
            + _migratror_hash(
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

    def __init__(self):
        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {}

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """If true don't act upon node

        Parameters
        ----------
        attrs : dict
            The node attributes

        Returns
        -------
        bool :
            True if node is to be skipped
        """
        return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        """Perform the migration, updating the ``meta.yaml``

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
    """Base class for Migrators"""

    name: str

    rerender = True

    # bump this if the migrator object needs a change mid migration
    migrator_version = 0

    allow_empty_commits = False

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
        pr_limit: int = 0,
        # TODO: Validate this?
        obj_version: int | None = None,
        piggy_back_migrations: Sequence[MiniMigrator] | None = None,
        check_solvable: bool = True,
        graph: nx.DiGraph | None = None,
        effective_graph: nx.DiGraph | None = None,
    ):
        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "pr_limit": pr_limit,
                "obj_version": obj_version,
                "piggy_back_migrations": piggy_back_migrations,
                "check_solvable": check_solvable,
                "graph": graph,
                "effective_graph": effective_graph,
            }

        self.piggy_back_migrations = piggy_back_migrations or []
        self._pr_limit = pr_limit
        self.obj_version = obj_version
        self.check_solvable = check_solvable

        if graph is None:
            self.graph = nx.DiGraph()
        else:
            self.graph = graph

        self.effective_graph = effective_graph

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

    def _reset_effective_graph(self, force=False):
        """This method is meant to be called by an non-abstract child class at the end
        of its __init__ method."""
        if self.effective_graph is None or force:
            self.effective_graph = _make_effective_graph(self.graph, self)
            self._init_kwargs["effective_graph"] = self.effective_graph

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
        """Utility method for getting a list of follow on packages"""
        return [
            a[1]
            for a in list(
                self.effective_graph.out_edges(feedstock_ctx.feedstock_name),
            )
        ][:limit]

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """If true don't act upon node

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
        # never run on archived feedstocks
        # don't run on things we've already done
        # don't run on bad nodes

        __name = attrs.get("name", "")

        def parse_already_pred() -> bool:
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
                logger.debug(f"{__name}: already PRed: uid: {migrator_uid}")
                if "PR" in attrs.get("pr_info", {}).get("PRed", [])[ind]:
                    if isinstance(
                        attrs.get("pr_info", {}).get("PRed", [])[ind]["PR"],
                        LazyJson,
                    ):
                        with attrs.get("pr_info", {}).get("PRed", [])[ind][
                            "PR"
                        ] as mg_attrs:
                            logger.debug(
                                "{}: already PRed: PR file: {}".format(
                                    __name, mg_attrs.file_name
                                ),
                            )

                            html_url = mg_attrs.get("html_url", "no url")

                            logger.debug(f"{__name}: already PRed: url: {html_url}")

            return already_pred

        if attrs.get("archived", False):
            logger.debug("%s: archived" % __name)

        bad_attr = _parse_bad_attr(attrs, not_bad_str_start)
        if bad_attr:
            logger.debug("%s: bad attr - %s", __name, bad_attr)

        return attrs.get("archived", False) or parse_already_pred() or bad_attr

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
            logger.exception(f"Invalid value for {attrs.get('conda-forge.yml', {})=}")
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
        """Perform the migration, updating the ``meta.yaml``

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
        """Create a PR message body

        Returns
        -------
        body: str
            The body of the PR message
            :param feedstock_ctx:
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
        """Create a commit message
        :param feedstock_ctx:
        """
        return f"migration: {self.__class__.__name__}"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        """Title for PR
        :param feedstock_ctx:
        """
        return "PR from Regro-cf-autotick-bot"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        """Branch to use on local and remote
        :param feedstock_context:
        """
        return "bot-pr"

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        """Make a unique id for this migrator and node attrs

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
        """Order to run migrations in

        Parameters
        ----------
        graph : nx.DiGraph
            The graph of migratable PRs

        Returns
        -------

        """
        top_level = {
            node
            for node in graph
            if not list(graph.predecessors(node))
            or list(graph.predecessors(node)) == [node]
        }
        return cyclic_topological_sort(graph, top_level)

    def set_build_number(self, filename: str) -> None:
        """Bump the build number of the specified recipe.

        Parameters
        ----------
        filename : str
            Path the the meta.yaml
        """
        with open(filename) as f:
            raw = f.read()

        new_myaml = update_build_number(
            raw,
            self.new_build_number,
            build_patterns=self.build_patterns,
        )

        with open(filename, "w") as f:
            f.write(new_myaml)

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
            }

        super().__init__(
            pr_limit,
            obj_version,
            piggy_back_migrations,
            check_solvable=check_solvable,
            graph=graph,
            effective_graph=effective_graph,
        )

        # IDK if this will be there so I am going to make it if needed
        if "outputs_lut" in self.graph.graph:
            self.outputs_lut = self.graph.graph["outputs_lut"]
        else:
            self.outputs_lut = make_outputs_lut_from_graph(self.graph)

        self.name = name
        self.top_level = top_level or set()
        self.cycles = set(cycles or [])
        self.ignored_deps_per_node = ignored_deps_per_node or {}

    def all_predecessors_issued_and_stale(self, attrs: "AttrsTypedDict") -> bool:
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
            else:
                # issued so check timestamp
                pr_index = pr_muids.index(muid)
                ts = (
                    payload.get("pr_info", {})
                    .get("PRed", [])[pr_index]
                    .get("PR", {})
                    .get("created_at", None)
                )
                state = (
                    payload.get("pr_info", {})
                    .get("PRed", [])[pr_index]
                    .get("PR", {"state": "open"})
                    .get("state", "")
                )
                if state == "open":
                    if ts is not None:
                        now = datetime.datetime.now(datetime.timezone.utc)
                        ts = dateutil.parser.parse(ts)
                        if now - ts < datetime.timedelta(days=14):
                            logger.debug(
                                "node %s has PR %s open for %s",
                                node,
                                muid.get("data", {}).get("name", None),
                                now - ts,
                            )
                            return False
                    else:
                        # no timestamp so keep things open
                        logger.debug(
                            "node %s has PR %s:%s with no timestamp",
                            node,
                            muid.get("data", {}).get("name", None),
                            payload.get("pr_info", {})
                            .get("PRed", [])[pr_index]["PR"]
                            .file_name,
                        )
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
                logger.debug("not yet built: %s" % node)
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
                logger.debug("not yet built: %s" % node)
                return True

        return False

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        name = attrs.get("name", "")

        if super().filter(attrs, "Upstream:"):
            logger.debug("filter %s: archived or done", name)
            return True

        if attrs.get("feedstock_name", None) not in self.graph:
            logger.debug("filter %s: node not in graph", name)
            return True

        # If in top level or in a cycle don't check for upstreams just build
        if (attrs["feedstock_name"] in self.top_level) or (
            attrs["feedstock_name"] in self.cycles
        ):
            return False

        # once all PRs are issued (not merged) and old propose the change in pin
        if name == "conda-forge-pinning" and self.all_predecessors_issued_and_stale(
            attrs=attrs,
        ):
            logger.debug("not filtered %s: pinning parents issued and stale", name)
            return False

        # Check if all upstreams have been built
        if self.predecessors_not_yet_built(attrs=attrs):
            logger.debug("filter %s: parents not built", name)
            return True

        return False

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        n = super().migrator_uid(attrs)
        n["name"] = self.name
        return n
