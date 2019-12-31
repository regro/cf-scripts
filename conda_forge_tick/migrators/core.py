"""Classes for migrating repos"""
import os
from typing import List, Any

import urllib.error

import re
import warnings
from itertools import permutations, product
import typing

import networkx as nx
import conda.exceptions
from conda.models.version import VersionOrder
from rever.tools import eval_version, hash_url, replace_in_file
from ..xonsh_utils import indir

from conda_build.source import provide
from conda_build.config import Config
from conda_build.api import render

import requests

from conda_forge_tick.path_lengths import cyclic_topological_sort
from conda_forge_tick.xonsh_utils import eval_xonsh, env
from conda_forge_tick.utils import (
    render_meta_yaml,
    frozen_to_json_friendly,
    as_iterable,
    parse_meta_yaml,
    CB_CONFIG,
)
from conda_forge_tick.contexts import MigratorContext, FeedstockContext

from typing import *

if typing.TYPE_CHECKING:
    from ..migrators_types import *
    from conda_forge_tick.utils import JsonFriendly

try:
    from conda_smithy.lint_recipe import NEEDED_FAMILIES
except ImportError:
    NEEDED_FAMILIES = ["gpl", "bsd", "mit", "apache", "psf"]


def _sanitized_muids(pred: List[dict]) -> List["JsonFriendly"]:
    l = []
    for pr in pred:
        d: "JsonFriendly" = {"data": pr["data"], "keys": pr["keys"]}
        l.append(d)
    return l


def _parse_bad_attr(attrs: "AttrsTypedDict", not_bad_str_start: str) -> bool:
    """Overlook some bad entries """
    bad = attrs.get("bad", False)
    if isinstance(bad, str):
        return not bad.startswith(not_bad_str_start)
    else:
        return bad


class MiniMigrator:
    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """ If true don't act upon node

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


class PipMigrator(MiniMigrator):
    bad_install = (
        "python setup.py install",
        "python -m pip install --no-deps --ignore-installed .",
    )

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        scripts = as_iterable(
            attrs.get("meta_yaml", {}).get("build", {}).get("script", []),
        )
        return not bool(set(self.bad_install) & set(scripts))

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            for b in self.bad_install:
                replace_in_file(
                    f"script: {b}",
                    "script: {{ PYTHON }} -m pip install . --no-deps -vv",
                    "meta.yaml",
                )


class LicenseMigrator(MiniMigrator):
    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        license = attrs.get("meta_yaml", {}).get("about", {}).get("license", "")
        license_fam = (
            attrs.get("meta_yaml", {})
            .get("about", {})
            .get("license_family", "")
            .lower()
            or license.lower().partition("-")[0].partition("v")[0]
        )
        if license_fam in NEEDED_FAMILIES and "license_file" not in attrs.get(
            "meta_yaml", {},
        ).get("about", {}):
            return False
        return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        # Use conda build to do all the downloading/extracting bits
        md = render(recipe_dir, config=Config(**CB_CONFIG))
        if not md:
            return
        md = md[0][0]
        # go into source dir
        cb_work_dir = provide(md)
        with indir(cb_work_dir):
            # look for a license file
            license_files = [
                s
                for s in os.listdir(".")
                if any(
                    s.lower().startswith(k) for k in ["license", "copying", "copyright"]
                )
            ]
        eval_xonsh(f"rm -r {cb_work_dir}")
        # if there is a license file in tarball update things
        if license_files:
            with indir(recipe_dir):
                """BSD 3-Clause License
                  Copyright (c) 2017, Anthony Scopatz
                  Copyright (c) 2018, The Regro Developers
                  All rights reserved."""
                with open("meta.yaml", "r") as f:
                    raw = f.read()
                lines = raw.splitlines()
                ptn = re.compile(r"(\s*?)" + "license:")
                for i, line in enumerate(lines):
                    m = ptn.match(line)
                    if m is not None:
                        break
                # TODO: Sketchy type assertion
                assert m is not None
                ws = m.group(1)
                if len(license_files) == 1:
                    replace_in_file(
                        line,
                        line + "\n" + ws + f"license_file: {list(license_files)[0]}",
                        "meta.yaml",
                    )
                else:
                    # note that this white space is not perfect but works for most of the situations
                    replace_in_file(
                        line,
                        line
                        + "\n"
                        + ws
                        + "license_file: \n"
                        + "".join(f"{ws*2}- {z} \n" for z in license_files),
                        "meta.yaml",
                    )

        # if license not in tarball do something!
        # check if github in dev url, then use that to get the license


class Migrator:
    """Base class for Migrators"""

    rerender = False

    # bump this if the migrator object needs a change mid migration
    migrator_version = 0

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
        obj_version: Optional[int] = None,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
    ):
        if piggy_back_migrations is None:
            piggy_back_migrations = []
        self.piggy_back_migrations = piggy_back_migrations
        self.pr_limit = pr_limit
        self.obj_version = obj_version
        self.ctx: MigratorContext = None

    def bind_to_ctx(self, migrator_ctx: MigratorContext) -> None:
        self.ctx = migrator_ctx

    def downstream_children(
        self, feedstock_ctx: FeedstockContext, limit: int = 5,
    ) -> List["PackageName"]:
        """Utility method for getting a list of follow on packages"""
        return [
            a[1]
            for a in list(
                self.ctx.effective_graph.out_edges(feedstock_ctx.package_name),
            )
        ][:limit]

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """ If true don't act upon node

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

        def parse_already_pred() -> bool:
            migrator_uid: "MigrationUidTypedDict" = typing.cast(
                "MigrationUidTypedDict",
                frozen_to_json_friendly(self.migrator_uid(attrs))["data"],
            )
            already_migrated_uids: typing.Iterable["MigrationUidTypedDict"] = (
                z["data"] for z in attrs.get("PRed", [])
            )
            return migrator_uid in already_migrated_uids

        return (
            attrs.get("archived", False)
            or parse_already_pred()
            or _parse_bad_attr(attrs, not_bad_str_start)
        )

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
        for mini_migrator in self.piggy_back_migrations:
            if not mini_migrator.filter(attrs):
                mini_migrator.migrate(recipe_dir, attrs, **kwargs)
        return self.migrator_uid(attrs)

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        """Create a PR message body

        Returns
        -------
        body: str
            The body of the PR message
            :param feedstock_ctx:
        """
        body = (
            "{}\n"
            "If this PR was opened in error or needs to be updated please add "
            "the `bot-rerun` label to this PR. The bot will close this PR and "
            "schedule another one.\n\n"
            "<sub>"
            "This PR was created by the [cf-regro-autotick-bot](https://github.com/regro/cf-scripts).\n"
            "The **cf-regro-autotick-bot** is a service to automatically "
            "track the dependency graph, migrate packages, and "
            "propose package version updates for conda-forge. "
            "If you would like a local version of this bot, you might consider using "
            "[rever](https://regro.github.io/rever-docs/). "
            "Rever is a tool for automating software releases and forms the "
            "backbone of the bot's conda-forge PRing capability. Rever is both "
            "conda (`conda install -c conda-forge rever`) and pip "
            "(`pip install re-ver`) installable.\n"
            "Finally, feel free to drop us a line if there are any "
            "[issues](https://github.com/regro/cf-scripts/issues)!\n"
            + f"This PR was generated by {self.ctx.session.circle_build_url}, please use this URL for debugging"
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

    def pr_head(self, feedstock_ctx: FeedstockContext) -> str:
        """Head for PR
        :param feedstock_ctx:
        """
        return f"{self.ctx.github_username}:{self.remote_branch(feedstock_ctx=feedstock_ctx)}"

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
            The unique id as a frozen_to_json_friendly (so it can be used as keys in dicts)
        """
        d: "MigrationUidTypedDict" = {
            "migrator_name": self.__class__.__name__,
            "migrator_version": self.migrator_version,
            "bot_rerun": False,
        }
        # Carveout for old migrators w/o obj_versions
        if self.obj_version:
            d["migrator_object_version"] = self.obj_version
        return d

    def order(
        self, graph: nx.DiGraph, total_graph: nx.DiGraph,
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

        for p, n in self.build_patterns:
            with open(filename, "r") as f:
                raw = f.read()
            lines = raw.splitlines()
            for i, line in enumerate(lines):
                m = p.match(line)
                if m is not None:
                    old_build_number = int(m.group(2))
                    new_build_number = self.new_build_number(old_build_number)
                    lines[i] = m.group(1) + n.format(new_build_number)
            upd = "\n".join(lines) + "\n"
            with open(filename, "w") as f:
                f.write(upd)

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


class Version(Migrator):
    """Migrator for version bumping of packages"""

    max_num_prs = 3
    patterns = (
        # filename, pattern, new
        # set the version
        ("meta.yaml", r"version:\s*[A-Za-z0-9._-]+", 'version: "$VERSION"'),
        (
            "meta.yaml",
            r"{%\s*set\s+version\s*=\s*[^\s]*\s*%}",
            '{% set version = "$VERSION" %}',
        ),
    )

    url_pat = re.compile(
        r"^( *)(-)?(\s*)url:\s*([^\s#]+?)\s*(?:(#.*)?\[([^\[\]]+)\])?(?(5)[^\(\)\n]*)(?(2)\n\1 \3.*)*$",
        flags=re.M,
    )
    r_url_pat = re.compile(
        r"^(\s*)(-)?(\s*)url:\s*(?:(#.*)?\[([^\[\]]+)\])?(?(4)[^\(\)]*?)\n(\1(?(2) \3)  -.*\n?)*",
        flags=re.M,
    )
    r_urls = re.compile(r"\s*-\s*(.+?)(?:#.*)?$", flags=re.M)

    migrator_version = 0

    # TODO: replace these types with a namedtuple so that it is clear what this is
    def find_urls(self, text: str) -> List[Tuple[Union[str, List[str]], str, str]]:
        """Get the URLs and platforms in a meta.yaml."""
        urls: List[Tuple[Union[str, List[str]], str, str]] = []
        for m in self.url_pat.finditer(text):
            urls.append((m.group(4), m.group(6), m.group()))
        for m in self.r_url_pat.finditer(text):
            if m is not None:
                r = self.r_urls.findall(m.group())
                urls.append((r, m.group(2), m.group()))
        return urls

    def get_hash_patterns(
        self,
        filename: str,
        urls: List[Tuple[Union[str, List[str]], str, str]],
        hash_type: str,
    ) -> Sequence[Tuple[str, str, str]]:
        """Get the patterns to replace hash for each platform."""
        pats: MutableSequence[Tuple[str, str, str]] = []
        checksum_names = [
            "hash_value",
            "hash",
            "hash_val",
            "sha256sum",
            "checksum",
            hash_type,
        ]
        for url, platform, line in urls:
            if isinstance(url, list):
                for u in url:
                    u = u.strip("'\"")
                    try:
                        hash_ = hash_url(u, hash_type)
                        break
                    except urllib.error.HTTPError:
                        continue
                else:
                    raise ValueError("Could not determine hash from recipe!")
            else:
                url = url.strip("'\"")
                hash_ = hash_url(url, hash_type)
            m = re.search(fr"\s*{hash_type}:(.+)", line)
            if m is None:
                p = fr"{hash_type}:\s*[0-9A-Fa-f]+"
                if platform:
                    p += fr"\s*(#.*)\[{platform}\](?(1)[^\(\)]*)$"
                else:
                    p += "$"
            else:
                p = "{}:{}$".format(hash_type, m.group(1))
            n = f"{hash_type}: {hash_}"
            if platform:
                n += f"  # [{platform}]"
            pats.append((filename, p, n))

            base1 = r"""{{%\s*set {checkname} = ['"][0-9A-Fa-f]+['"] %}}"""
            base2 = '{{% set {checkname} = "{h}" %}}'
            for cn in checksum_names:
                pats.append(
                    (
                        "meta.yaml",
                        base1.format(checkname=cn),
                        base2.format(checkname=cn, h=hash_),
                    ),
                )
        return pats

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        # if no new version do nothing
        if "new_version" not in attrs:
            return True
        conditional = super().filter(attrs)
        result = bool(
            conditional  # if archived/finished
            or len(
                [
                    k
                    for k in attrs.get("PRed", [])
                    if k["data"].get("migrator_name") == "Version"
                    # The PR is the actual PR itself
                    and k.get("PR", {}).get("state", None) == "open"
                ],
            )
            > self.max_num_prs
            or not attrs.get("new_version"),  # if no new version
        )
        try:
            version_filter = (
                # if new version is less than current version
                (
                    VersionOrder(str(attrs["new_version"]))
                    <= VersionOrder(str(attrs.get("version", "0.0.0")))
                )
                # if PRed version is greater than newest version
                or any(
                    VersionOrder(self._extract_version_from_muid(h))
                    >= VersionOrder(str(attrs["new_version"]))
                    for h in attrs.get("PRed", set())
                )
            )
        except conda.exceptions.InvalidVersionSpec as e:
            warnings.warn(
                f"Failed to filter to to invalid version for {attrs}\nException: {e}",
            )
            version_filter = True
        return result or version_filter

    def migrate(
        self,
        recipe_dir: str,
        attrs: "AttrsTypedDict",
        hash_type: str = "sha256",
        **kwargs: Any,
    ) -> "MigrationUidTypedDict":
        # Render with new version but nothing else
        version = attrs["new_version"]
        assert isinstance(version, str)
        with indir(recipe_dir):
            with open("meta.yaml", "r") as fp:
                text = fp.read()
        res = re.search(r"\s*-?\s*url:.*?\n( {4}-.*\n?)*", text)
        if res:
            url = res.group()
        else:
            raise ValueError("Could not match url")
        if "cran.r-project.org/src/contrib" in url or "cran_mirror" in url:
            version = version.replace("_", "-")
        with indir(recipe_dir), env.swap(VERSION=version):
            for f, p, n in self.patterns:
                p = eval_version(p)
                n = eval_version(n)
                replace_in_file(p, n, f)
            with open("meta.yaml", "r") as fp:
                text = fp.read()

        # render the text and check that the URL exists, if it doesn't try variations
        # if variations then update url
        rendered = parse_meta_yaml(render_meta_yaml(text))
        # only run for single url recipes as the moment
        if (
            isinstance(rendered["source"], dict)
            and isinstance(rendered["source"].get("url", []), str)
            and requests.get(rendered["source"]["url"]).status_code != 200
        ):
            with indir(recipe_dir):
                for (a, b), (c, d) in product(
                    permutations(["v{{ v", "{{ v"]), permutations([".zip", ".tar.gz"])
                ):
                    inner_text = text.replace(a, b).replace(c, d)
                    rendered = parse_meta_yaml(render_meta_yaml(inner_text))
                    if requests.get(rendered["source"]["url"]).status_code == 200:
                        text = inner_text
                        # The above clauses could do bad things the version
                        # itself
                        text = text.replace("version: v{{ v", "version: {{ v")
                        with open("meta.yaml", "w") as fp:
                            fp.write(text)
                        break
        # Get patterns to replace checksum for each platform
        rendered_text = render_meta_yaml(text)
        urls = self.find_urls(rendered_text)
        new_patterns = self.get_hash_patterns("meta.yaml", urls, hash_type)

        with indir(recipe_dir):
            for f, p, n in new_patterns:
                p = eval_version(p)
                n = eval_version(n)
                replace_in_file(p, n, f)
            self.set_build_number("meta.yaml")
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        pred = [
            (name, self.ctx.effective_graph.nodes[name]["payload"]["new_version"])
            for name in list(
                self.ctx.effective_graph.predecessors(feedstock_ctx.package_name),
            )
        ]
        body = super().pr_body(feedstock_ctx)
        # TODO: note that the closing logic needs to be modified when we
        #  issue PRs into other branches for backports
        open_version_prs = [
                    muid['PR']
                    for muid in feedstock_ctx.attrs.get("PRed", [])
                    if muid["data"].get("migrator_name") == "Version"
                    # The PR is the actual PR itself
                    and muid.get("PR", {}).get("state", None) == "open"
                ],
        muid: dict
        body = body.format(
            "It is very likely that the current package version for this "
            "feedstock is out of date.\n"
            "Notes for merging this PR:\n"
            "1. Feel free to push to the bot's branch to update this PR if needed.\n"
            "2. The bot will almost always only open one PR per version.\n"
            "Checklist before merging this PR:\n"
            "- [ ] Dependencies have been updated if changed\n"
            "- [ ] Tests have passed \n"
            "- [ ] Updated license if changed and `license_file` is packaged \n"
            "\n"
            "Note that the bot will stop issuing PRs if more than {} Version bump PRs "
            "generated by the bot are open. If you don't want to package a particular "
            "version please close the PR.\n\n"
            "{}".format(self.max_num_prs, '\n'.join([f"Closes: #{muid['number']}" for muid in open_version_prs])),
        )
        # Statement here
        template = (
            "|{name}|{new_version}|[![Anaconda-Server Badge]"
            "(https://img.shields.io/conda/vn/conda-forge/{name}.svg)]"
            "(https://anaconda.org/conda-forge/{name})|\n"
        )
        if len(pred) > 0:
            body += (
                "\n\nHere is a list of all the pending dependencies (and their "
                "versions) for this repo. "
                "Please double check all dependencies before merging.\n\n"
            )
            # Only add the header row if we have content.
            # Otherwise the rendered table in the github comment
            # is empty which is confusing
            body += (
                "| Name | Upstream Version | Current Version |\n"
                "|:----:|:----------------:|:---------------:|\n"
            )
        for p in pred:
            body += template.format(name=p[0], new_version=p[1])
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        assert isinstance(feedstock_ctx.attrs["new_version"], str)
        return "updated v" + feedstock_ctx.attrs["new_version"]

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        assert isinstance(feedstock_ctx.attrs["new_version"], str)
        return feedstock_ctx.package_name + " v" + feedstock_ctx.attrs["new_version"]

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        assert isinstance(feedstock_ctx.attrs["new_version"], str)
        return feedstock_ctx.attrs["new_version"]

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        n = super().migrator_uid(attrs)
        assert isinstance(attrs["new_version"], str)
        n["version"] = attrs["new_version"]
        return n

    def _extract_version_from_muid(self, h: dict) -> str:
        return h.get("version", "0.0.0")

    @classmethod
    def new_build_number(cls, old_build_number: int) -> int:
        return 0

    def order(
        self, graph: nx.DiGraph, total_graph: nx.DiGraph,
    ) -> Sequence["PackageName"]:
        return sorted(
            graph, key=lambda x: (len(nx.descendants(total_graph, x)), x), reverse=True
        )


class GraphMigrator(Migrator):
    def __init__(
        self,
        *,
        name: Optional[str] = None,
        graph: nx.DiGraph = None,
        pr_limit: int = 0,
        obj_version: Optional[int] = None,
        piggy_back_migrations: Optional[Sequence[MiniMigrator]] = None,
    ):
        super().__init__(pr_limit, obj_version, piggy_back_migrations)
        # TODO: Grab the graph from the migrator ctx
        if graph is None:
            self.graph = nx.DiGraph()
        else:
            self.graph = graph
        self.name = name

    def predecessors_not_yet_built(self, attrs: "AttrsTypedDict") -> bool:
        # Check if all upstreams have been built
        for node in self.graph.predecessors(attrs["feedstock_name"]):
            payload = self.graph.nodes[node]["payload"]
            muid = frozen_to_json_friendly(self.migrator_uid(payload))
            if muid not in _sanitized_muids(
                payload.get("PRed", [])
            ) and not payload.get("archived", False,):
                return True
            # This is due to some PRed_json loss due to bad graph deploy outage
            for m_pred_json in payload.get("PRed", []):
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
                return True
        return False


class Replacement(Migrator):
    """Migrator for replacing one package with another.

    Parameters
    ----------
    old_pkg : str
        The package to be replaced.
    new_pkg : str
        The package to replace the `old_pkg`.
    rationale : str
        The reason the for the migration. Should be a full statement.
    """

    migrator_version = 0
    rerender = True

    def __init__(
        self,
        *,
        old_pkg: "PackageName",
        new_pkg: "PackageName",
        rationale: str,
        pr_limit: int = 0,
    ):
        super().__init__(pr_limit)
        self.old_pkg = old_pkg
        self.new_pkg = new_pkg
        self.pattern = re.compile(r"\s*-\s*(%s)(\s+|$)" % old_pkg)
        self.packages = {old_pkg}
        self.rationale = rationale

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        return (
            super().filter(attrs) or len(attrs.get("req", set()) & self.packages) == 0
        )

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        with open(os.path.join(recipe_dir, "meta.yaml")) as f:
            raw = f.read()
        lines = raw.splitlines()
        n = False
        for i, line in enumerate(lines):
            m = self.pattern.match(line)
            if m is not None:
                lines[i] = lines[i].replace(m.group(1), self.new_pkg)
                n = True
        if not n:
            return False
        upd = "\n".join(lines) + "\n"
        with open(os.path.join(recipe_dir, "meta.yaml"), "w") as f:
            f.write(upd)
        self.set_build_number(os.path.join(recipe_dir, "meta.yaml"))
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            "I noticed that this recipe depends on `%s` instead of \n"
            "`%s`. %s \n"
            "This PR makes this change."
            "\n"
            "Notes and instructions for merging this PR:\n"
            "1. Make sure that the recipe can indeed only depend on `%s`. \n"
            "2. Please merge the PR only after the tests have passed. \n"
            "3. Feel free to push to the bot's branch to update this PR if "
            "needed. \n" % (self.old_pkg, self.new_pkg, self.rationale, self.new_pkg),
        )
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return f"use {self.new_pkg} instead of {self.old_pkg}"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return f"Suggestion: depend on {self.new_pkg} instead of {self.old_pkg}"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return f"{self.old_pkg}-to-{self.new_pkg}-migration"
