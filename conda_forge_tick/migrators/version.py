import re
import os
import typing
import pprint
import jinja2
import collections.abc
import hashlib
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
from conda_forge_tick.recipe_parser import CONDA_SELECTOR, CondaMetaYAML

if typing.TYPE_CHECKING:
    from conda_forge_tick.migrators_types import (
        MigrationUidTypedDict,
        AttrsTypedDict,
    )

EXTS = ['.tar.gz', '.zip', '.tar.bz2', '.tar']
CHECKSUM_NAMES = [
    "hash_value",
    "hash",
    "hash_val",
    "sha256sum",
    "checksum",
]


def _gen_key_selector(dct, key):
    for k in dct:
        if key in k:
            yield k


def _is_r_url(url):
    if (
        "cran.r-project.org/src/contrib" in url or
        "cran_mirror" in url
    ):
        return True
    else:
        return False


def _has_r_url(curr_val):
    if isinstance(curr_val, collections.abc.MutableSequence):
        for i in range(len(curr_val)):
            return _has_r_url(curr_val[i])
    elif isinstance(curr_val, collections.abc.MutableMapping):
        for key in _gen_key_selector(curr_val, 'url'):
            return _has_r_url(curr_val[key])
    elif isinstance(curr_val, str):
        return _is_r_url(curr_val)
    else:
        return False


def _compile_all_selectors(cmeta, src):
    selectors = [None]
    for key in cmeta.jinja2_vars:
        if CONDA_SELECTOR in key:
            selectors.append(key.split(CONDA_SELECTOR)[1])
    for key in src:
        if CONDA_SELECTOR in key:
            selectors.append(key.split(CONDA_SELECTOR)[1])
    return set(selectors)


def _try_url_and_hash_it(url, hash_type):
    print("    downloading url:", url)

    resp = requests.get(url)
    print("    response:", resp.status_code)
    if resp.status_code == 200:
        ha = getattr(hashlib, hash_type)
        new_hash = ha(resp.content).hexdigest()
        print("    hash:", new_hash)
        return new_hash

    return None


def _get_new_url_tmpl_and_hash(url_tmpl, context, hash_type):
    url = (
        jinja2
        .Template(url_tmpl)
        .render(**context)
    )
    new_hash = _try_url_and_hash_it(url, hash_type)

    if new_hash is None:
        # try some stuff
        for (vhave, vrep), (exthave, extrep) in product(
            permutations(["v{{ v", "{{ v"]),
            permutations(EXTS, 2),
        ):
            new_url_tmpl = (
                url_tmpl
                .replace(vhave, vrep)
                .replace(exthave, extrep)
            )

            url = (
                jinja2
                .Template(new_url_tmpl)
                .render(**context)
            )
            new_hash = _try_url_and_hash_it(url, hash_type)
            if new_hash is not None:
                break
    else:
        new_url_tmpl = url_tmpl

    return new_url_tmpl, new_hash


def _try_replace_hash(hash_key, cmeta, src, selector, hash_type, new_hash):
    _replaced_hash = False
    if '{{' in src[hash_key] and '}}' in src[hash_key]:
        # it's jinja2 :(
        cnames = CHECKSUM_NAMES + [hash_type]
        for cname in cnames:
            if selector is not None:
                key = cname + CONDA_SELECTOR + selector
                if key in cmeta.jinja2_vars:
                    cmeta.jinja2_vars[key] = new_hash
                    _replaced_hash = True
                    break

            if cname in cmeta.jinja2_vars:
                cmeta.jinja2_vars[cname] = new_hash
                _replaced_hash = True
                break

    else:
        _replaced_hash = True
        src[hash_key] = new_hash

    return _replaced_hash


def _try_to_update_version(cmeta, src, hash_type):
    if not any('url' in k for k in src):
        return False

    ha = getattr(hashlib, hash_type, None)
    if ha is None:
        return False

    updated_version = False

    # first we compile all selectors
    possible_selectors = _compile_all_selectors(cmeta, src)

    # now loop through them and try to construct sets of
    # 1. urls
    # 2. hashes
    # 3. jinja2 contexts
    # these are then updated

    for selector in possible_selectors:
        print("    selector:", selector)
        url_key = 'url'
        if selector is not None:
            for key in _gen_key_selector(src, 'url'):
                if selector in key:
                    url_key = key

        if url_key not in src:
            continue

        hash_key = hash_type
        if selector is not None:
            for key in _gen_key_selector(src, hash_type):
                if selector in key:
                    hash_key = key

        if hash_key not in src:
            continue

        context = {}
        for key, val in cmeta.jinja2_vars.items():
            if CONDA_SELECTOR in key:
                if selector is not None and selector in key:
                    context[key.split(CONDA_SELECTOR)[0]] = val
            else:
                context[key] = val

        # now try variations of the url to get the hash
        if isinstance(src[url_key], collections.abc.MutableSequence):
            for url_ind, url_tmpl in enumerate(src[url_key]):
                new_url_tmpl, new_hash = _get_new_url_tmpl_and_hash(
                    url_tmpl,
                    context,
                    hash_type,
                )
                if new_hash is not None:
                    break
        else:
            new_url_tmpl, new_hash = _get_new_url_tmpl_and_hash(
                src[url_key],
                context,
                hash_type,
            )

        # now try to replace the hash
        if new_hash is not None:
            _replaced_hash = _try_replace_hash(
                hash_key,
                cmeta,
                src,
                selector,
                hash_type,
                new_hash,
            )
            if _replaced_hash:
                if isinstance(src[url_key], collections.abc.MutableSequence):
                    src[url_key][url_ind] = new_url_tmpl
                else:
                    src[url_key] = new_url_tmpl
            else:
                new_hash = None

        updated_version |= (new_hash is not None)

    return updated_version


class Version(Migrator):
    """Migrator for version bumping of packages"""

    max_num_prs = 3
    migrator_version = 0

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

        with open(os.path.join(recipe_dir, "meta.yaml"), 'r') as fp:
            cmeta = CondaMetaYAML(fp.read())

        version = attrs["new_version"]
        assert isinstance(version, str)

        # mangle the version if it is R
        r_url = _has_r_url(cmeta.meta['source'])
        for key, val in cmeta.jinja2_vars.items():
            if isinstance(val, str):
                r_url |= _is_r_url(val)
        if r_url:
            version = version.replace("_", "-")

        # replace the version
        # FIXME: move to loop with selectors
        if 'version' in cmeta.jinja2_vars:
            cmeta.jinja2_vars['version'] = version
        else:
            cmeta.meta['source']['version'] = version

        if isinstance(cmeta.meta['source'], collections.abc.MutableSequence):
            did_update = False
            for src in cmeta.meta['source']:
                did_update |= _try_to_update_version(cmeta, src, hash_type)
        else:
            did_update = _try_to_update_version(cmeta, cmeta.meta['source'], hash_type)

        if did_update:
            with indir(recipe_dir):
                with open('meta.yaml', 'w') as fp:
                    cmeta.dump(fp)
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
            graph, key=lambda x: (len(nx.descendants(total_graph, x)), x), reverse=True,
        )
