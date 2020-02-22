import re
import typing
import random
from typing import (
    List,
    Tuple,
    Union,
    Sequence,
    MutableSequence,
    Any,
)
import urllib.error
import warnings
from itertools import permutations, product

import requests
import networkx as nx
import conda.exceptions
from conda.models.version import VersionOrder
from rever.tools import eval_version, hash_url, replace_in_file

from conda_forge_tick.xonsh_utils import env
from conda_forge_tick.migrators.core import Migrator
from conda_forge_tick.contexts import FeedstockContext
from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.utils import render_meta_yaml, parse_meta_yaml

if typing.TYPE_CHECKING:
    from conda_forge_tick.migrators_types import (
        MigrationUidTypedDict,
        AttrsTypedDict,
    )


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
        r"^( *)(-)?(\s*)url:\s*([^\s#]+?)\s*(?:(#.*)?\[([^\[\]]+)\])?(?(5)[^\(\)\n]*)(?(2)\n\1 \3.*)*$",  # noqa
        flags=re.M,
    )
    r_url_pat = re.compile(
        r"^(\s*)(-)?(\s*)url:\s*(?:(#.*)?\[([^\[\]]+)\])?(?(4)[^\(\)]*?)\n(\1(?(2) \3)  -.*\n?)*",  # noqa
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
                p = f"{hash_type}: {m.group(1)}$"
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
        if "new_version" not in attrs or not attrs["new_version"]:
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
                    permutations(["v{{ v", "{{ v"]), permutations([".zip", ".tar.gz"]),
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
            muid["PR"]
            for muid in feedstock_ctx.attrs.get("PRed", [])
            if muid["data"].get("migrator_name") == "Version"
            # The PR is the actual PR itself
            and muid.get("PR", {}).get("state", None) == "open"
        ]

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
            "{}".format(
                self.max_num_prs,
                "\n".join([f"Closes: #{muid['number']}" for muid in open_version_prs]),
            ),
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
        # TODO: turn False to True when we default to automerge
        if (
            feedstock_ctx.attrs.get("conda-forge.yml", {})
            .get("bot", {})
            .get("automerge", False)
        ):
            add_slug = "[bot-automerge] "
        else:
            add_slug = ""

        return (
            add_slug
            + feedstock_ctx.package_name
            + " v"
            + feedstock_ctx.attrs["new_version"]
        )

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
            graph,
            # FIXME - we should flag bad version PRs instead
            # key=lambda x: (len(nx.descendants(total_graph, x)), x),
            key=lambda x: random.uniform(0, 1),
            reverse=True,
        )
