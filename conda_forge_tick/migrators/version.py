import os
import typing
import re
import io
import jinja2
import collections.abc
import hashlib
import pprint
import functools
import random
import traceback
from typing import (
    Sequence,
    MutableMapping,
    Any,
    List,
)
import warnings
import logging

import networkx as nx
import conda.exceptions
from conda.models.version import VersionOrder

from conda_forge_tick.migrators.core import Migrator
from conda_forge_tick.contexts import FeedstockContext
from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.recipe_parser import CONDA_SELECTOR, CondaMetaYAML
from conda_forge_tick.url_transforms import gen_transformed_urls
from conda_forge_tick.hashing import hash_url
from conda_forge_tick.utils import sanitize_string

if typing.TYPE_CHECKING:
    from conda_forge_tick.migrators_types import (
        MigrationUidTypedDict,
        AttrsTypedDict,
        PackageName,
    )

CHECKSUM_NAMES = [
    "hash_value",
    "hash",
    "hash_val",
    "sha256sum",
    "checksum",
]

# matches valid jinja2 vars
JINJA2_VAR_RE = re.compile("{{ ((?:[a-zA-Z]|(?:_[a-zA-Z0-9]))[a-zA-Z0-9_]*) }}")

logger = logging.getLogger("conda_forge_tick.migrators.version")


def _gen_key_selector(dct: MutableMapping, key: str):
    for k in dct:
        if k == key or (CONDA_SELECTOR in k and k.split(CONDA_SELECTOR)[0] == key):
            yield k


def _recipe_has_git_url(cmeta):
    found_git_url = False
    for src_key in _gen_key_selector(cmeta.meta, "source"):
        if isinstance(cmeta.meta[src_key], collections.abc.MutableSequence):
            for src in cmeta.meta[src_key]:
                for git_url_key in _gen_key_selector(src, "git_url"):
                    found_git_url = True
                    break
        else:
            for git_url_key in _gen_key_selector(cmeta.meta[src_key], "git_url"):
                found_git_url = True
                break

    return found_git_url


def _recipe_has_url(cmeta):
    found_url = False
    for src_key in _gen_key_selector(cmeta.meta, "source"):
        if isinstance(cmeta.meta[src_key], collections.abc.MutableSequence):
            for src in cmeta.meta[src_key]:
                for url_key in _gen_key_selector(src, "url"):
                    found_url = True
                    break
        else:
            for url_key in _gen_key_selector(cmeta.meta[src_key], "url"):
                found_url = True
                break

    return found_url


def _is_r_url(url: str):
    if "cran.r-project.org/src/contrib" in url or "cran_mirror" in url:
        return True
    else:
        return False


def _has_r_url(curr_val: Any):
    has_it = False
    if isinstance(curr_val, collections.abc.MutableSequence):
        for i in range(len(curr_val)):
            has_it = has_it or _has_r_url(curr_val[i])
    elif isinstance(curr_val, collections.abc.MutableMapping):
        for key in _gen_key_selector(curr_val, "url"):
            has_it = has_it or _has_r_url(curr_val[key])
    elif isinstance(curr_val, str):
        has_it = has_it or _is_r_url(curr_val)

    return has_it


def _compile_all_selectors(cmeta: Any, src: str):
    selectors = [None]
    for key in cmeta.jinja2_vars:
        if CONDA_SELECTOR in key:
            selectors.append(key.split(CONDA_SELECTOR)[1])
    for key in src:
        if CONDA_SELECTOR in key:
            selectors.append(key.split(CONDA_SELECTOR)[1])
    return set(selectors)


def _try_url_and_hash_it(url: str, hash_type: str):
    logger.debug("downloading url: %s", url)

    try:
        new_hash = hash_url(url, timeout=120, hash_type=hash_type)

        if new_hash is None:
            logger.debug("url does not exist or hashing took too long: %s", url)
            return None

        logger.debug("hash: %s", new_hash)
        return new_hash
    except Exception as e:
        logger.debug("hashing url failed: %s", repr(e))
        return None


def _render_jinja2(tmpl, context):
    return jinja2.Template(tmpl, undefined=jinja2.StrictUndefined).render(**context)


def _get_new_url_tmpl_and_hash(url_tmpl: str, context: MutableMapping, hash_type: str):
    logger.info(
        "hashing URL template: %s",
        url_tmpl,
    )
    try:
        logger.info(
            "rendered URL: %s",
            _render_jinja2(url_tmpl, context),
        )
    except jinja2.UndefinedError:
        logger.info("initial URL template does not render")
        pass

    try:
        url = _render_jinja2(url_tmpl, context)
        new_hash = _try_url_and_hash_it(url, hash_type)
        if new_hash is not None:
            return url_tmpl, new_hash
    except jinja2.UndefinedError:
        pass

    new_url_tmpl = None
    new_hash = None

    for new_url_tmpl in gen_transformed_urls(url_tmpl):
        try:
            url = _render_jinja2(new_url_tmpl, context)
            new_hash = _try_url_and_hash_it(url, hash_type)
        except jinja2.UndefinedError:
            new_hash = None

        if new_hash is not None:
            break

    return new_url_tmpl, new_hash


def _try_replace_hash(
    hash_key: str,
    cmeta: Any,
    src: MutableMapping,
    selector: str,
    hash_type: str,
    new_hash: str,
):
    _replaced_hash = False
    if "{{" in src[hash_key] and "}}" in src[hash_key]:
        # it's jinja2 :(
        cnames = set(
            CHECKSUM_NAMES
            + [hash_type]
            + list(set(JINJA2_VAR_RE.findall(src[hash_key]))),
        )
        for cname in cnames:
            if selector is not None:
                key = cname + CONDA_SELECTOR + selector
                if key in cmeta.jinja2_vars:
                    cmeta.jinja2_vars[key] = new_hash
                    logger.info(
                        "jinja2 w/ new hash: %s",
                        pprint.pformat(cmeta.jinja2_vars),
                    )
                    _replaced_hash = True
                    break

            if cname in cmeta.jinja2_vars:
                cmeta.jinja2_vars[cname] = new_hash
                logger.info("jinja2 w/ new hash: %s", pprint.pformat(cmeta.jinja2_vars))
                _replaced_hash = True
                break

    else:
        _replaced_hash = True
        src[hash_key] = new_hash
        logger.info("source w/ new hash: %s", pprint.pformat(src))

    return _replaced_hash


def _try_to_update_version(cmeta: Any, src: str, hash_type: str):
    errors = set()

    if len(src) == 1 and all("path" in k for k in src):
        return None, errors

    if not any("url" in k for k in src):
        errors.add("no URLs in the source section")
        return False, errors

    ha = getattr(hashlib, hash_type, None)
    if ha is None:
        errors.add("invalid hash type %s" % hash_type)
        return False, errors

    updated_version = True

    # first we compile all selectors
    possible_selectors = _compile_all_selectors(cmeta, src)

    # now loop through them and try to construct sets of
    # 1. urls
    # 2. hashes
    # 3. jinja2 contexts
    # these are then updated

    for selector in possible_selectors:
        # url and hash keys
        logger.info("selector: %s", selector)
        url_key = "url"
        if selector is not None:
            for key in _gen_key_selector(src, "url"):
                if selector in key:
                    url_key = key

        if url_key not in src:
            logger.info("src skipped url_key: %s", src)
            continue

        hash_key = None
        for _hash_type in {"md5", "sha256", hash_type}:
            if selector is not None:
                for key in _gen_key_selector(src, _hash_type):
                    if selector in key:
                        hash_key = key
                        hash_type = _hash_type
                        break

                if hash_key is not None:
                    break

            if _hash_type in src:
                hash_key = _hash_type
                hash_type = _hash_type
                break

        if hash_key is None:
            logger.info("src skipped no hash key: %s %s", hash_type, src)
            continue

        # jinja2 stuff
        context = {}
        for key, val in cmeta.jinja2_vars.items():
            if CONDA_SELECTOR in key:
                if selector is not None and selector in key:
                    context[key.split(CONDA_SELECTOR)[0]] = val
            else:
                context[key] = val
        # this pulls out any jinja2 expressions that are not constans
        # e.g. bits of jinja2 that extract version parts
        evaled_context = cmeta.eval_jinja2_exprs(context)
        logger.info("jinja2 context: %s", pprint.pformat(context))
        logger.info("evaluated jinja2 vars: %s", pprint.pformat(evaled_context))
        context.update(evaled_context)
        logger.info("updated jinja2 context: %s", pprint.pformat(context))

        # get all of the possible variables in the url
        # if we do not have them or any selector versions, then
        # we are not updating something so fail
        jinja2_var_set = set()
        if isinstance(src[url_key], collections.abc.MutableSequence):
            for url_tmpl in src[url_key]:
                jinja2_var_set |= set(JINJA2_VAR_RE.findall(url_tmpl))
        else:
            jinja2_var_set |= set(JINJA2_VAR_RE.findall(src[url_key]))

        jinja2_var_set |= set(JINJA2_VAR_RE.findall(src[hash_key]))

        skip_this_selector = False
        for var in jinja2_var_set:
            possible_keys = list(_gen_key_selector(cmeta.jinja2_vars, var)) + list(
                _gen_key_selector(evaled_context, var),
            )
            if len(possible_keys) == 0:
                if var == "cran_mirror":
                    context["cran_mirror"] = "https://cran.r-project.org"
                else:
                    logger.critical("jinja2 variable %s is missing!", var)
                    errors.add(
                        "missing jinja2 variable '%s' for selector '%s'"
                        % (var, selector),
                    )
                    updated_version = False
                    break

            # we have a variable, but maybe not this selector?
            # that's ok
            if var not in context:
                skip_this_selector = True

        if skip_this_selector:
            continue

        logger.info("url key: %s", url_key)
        logger.info("hash key: %s", hash_key)

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
                    errors.add("could not hash URL template '%s'" % url_tmpl)
        else:
            new_url_tmpl, new_hash = _get_new_url_tmpl_and_hash(
                src[url_key],
                context,
                hash_type,
            )
            if new_hash is None:
                errors.add("could not hash URL template '%s'" % src[url_key])

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
                    logger.info("source w/ new url: %s", pprint.pformat(src[url_key]))

                else:
                    src[url_key] = new_url_tmpl
                    logger.info("source w/ new url: %s", pprint.pformat(src))
            else:
                new_hash = None
                errors.add(
                    "could not replace the hash in the recipe "
                    "for URL template '%s'" % new_url_tmpl,
                )

        if new_hash is not None:
            logger.info("new URL template: %s", new_url_tmpl)

        logger.info("new URL hash: %s", new_hash)

        updated_version &= new_hash is not None

    return updated_version, errors


def _fmt_error_message(errors, version):
    msg = (
        "The recipe did not change in the version migration, a URL did "
        "not hash, or there is jinja2 syntax the bot cannot handle!\n\n"
        "Please check the URLs in your recipe with version '%s' to make sure "
        "they exist!\n\n" % version
    )
    if len(errors) > 0:
        msg += "We also found the following errors:\n\n - %s" % (
            "\n - ".join(e for e in errors)
        )
        msg += "\n"
    return sanitize_string(msg)


class Version(Migrator):
    """Migrator for version bumping of packages"""

    max_num_prs = 3
    migrator_version = 0
    rerender = True
    name = "Version"

    def __init__(self, python_nodes, *args, **kwargs):
        self.python_nodes = python_nodes
        if "check_solvable" in kwargs:
            kwargs.pop("check_solvable")
        super().__init__(*args, **kwargs, check_solvable=False)

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        # if no new version do nothing
        if "new_version" not in attrs or not attrs["new_version"]:
            return True

        # if no jinja2 version, then move on
        if "raw_meta_yaml" in attrs and "{% set version" not in attrs["raw_meta_yaml"]:
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
            name = attrs.get("name", "")
            warnings.warn(
                f"Failed to filter to to invalid version for {name}\nException: {e}",
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
        errors = set()

        version = attrs["new_version"]

        # record the attempt
        if "new_version_attempts" not in attrs:
            attrs["new_version_attempts"] = {}
        if version not in attrs["new_version_attempts"]:
            attrs["new_version_attempts"][version] = 0
        attrs["new_version_attempts"][version] += 1
        if "new_version_errors" not in attrs:
            attrs["new_version_errors"] = {}

        if not isinstance(version, str):
            errors.add(
                "the version '%s' is not a string and must be for the bot" % version,
            )
            attrs["new_version_errors"][version] = _fmt_error_message(errors, version)
            logger.critical(
                "the version '%s' is not a string and must be for the bot",
                version,
            )
            return {}

        try:
            with open(os.path.join(recipe_dir, "meta.yaml")) as fp:
                cmeta = CondaMetaYAML(fp.read())
        except Exception as e:
            tb = io.StringIO()
            traceback.print_tb(e.__traceback__, file=tb)
            tb.seek(0)
            tb = tb.read()
            attrs["new_version_errors"][version] = sanitize_string(
                "We found a problem parsing the recipe for version '"
                + version
                + "': \n\n"
                + repr(e)
                + "\n\ntraceback:\n"
                + tb,
            )
            logger.critical(
                "We found a problem parsing the recipe: \n\n%s\n\n%s",
                str(e),
                tb,
            )
            return {}

        # cache round-tripped yaml for testing later
        s = io.StringIO()
        cmeta.dump(s)
        s.seek(0)
        old_meta_yaml = s.read()

        # if is a git url, then we error
        if _recipe_has_git_url(cmeta) and not _recipe_has_url(cmeta):
            logger.critical("Migrations do not work on `git_url`s!")
            errors.add("migrations do not work on `git_url`s")
            attrs["new_version_errors"][version] = _fmt_error_message(errors, version)
            return {}

        # mangle the version if it is R
        r_url = False
        for src_key in _gen_key_selector(cmeta.meta, "source"):
            r_url |= _has_r_url(cmeta.meta[src_key])
        for key, val in cmeta.jinja2_vars.items():
            if isinstance(val, str):
                r_url |= _is_r_url(val)
        if r_url:
            version = version.replace("_", "-")

        # replace the version
        if "version" in cmeta.jinja2_vars:
            # cache old version for testing later
            old_version = cmeta.jinja2_vars["version"]
            cmeta.jinja2_vars["version"] = version
        else:
            logger.critical(
                "Migrations do not work on versions not specified with jinja2!",
            )
            errors.add("migrations do not work on versions not specified with jinja2")
            attrs["new_version_errors"][version] = _fmt_error_message(errors, version)
            return {}

        if len(list(_gen_key_selector(cmeta.meta, "source"))) > 0:
            did_update = True
            for src_key in _gen_key_selector(cmeta.meta, "source"):
                if isinstance(cmeta.meta[src_key], collections.abc.MutableSequence):
                    for src in cmeta.meta[src_key]:
                        _did_update, _errors = _try_to_update_version(
                            cmeta,
                            src,
                            hash_type,
                        )
                        if _did_update is not None:
                            did_update &= _did_update
                            errors |= _errors
                else:
                    _did_update, _errors = _try_to_update_version(
                        cmeta,
                        cmeta.meta[src_key],
                        hash_type,
                    )
                    if _did_update is not None:
                        did_update &= _did_update
                        errors |= _errors
                if _errors:
                    logger.critical("%s", _errors)
        else:
            did_update = False
            errors.add("no source sections found in the recipe")
            logger.critical("no source sections found in the recipe")

        if did_update:
            # if the yaml did not change, then we did not migrate actually
            cmeta.jinja2_vars["version"] = old_version
            s = io.StringIO()
            cmeta.dump(s)
            s.seek(0)
            still_the_same = s.read() == old_meta_yaml
            cmeta.jinja2_vars["version"] = version  # put back version

            if still_the_same and old_version != version:
                did_update = False
                errors.add(
                    "recipe did not appear to change even "
                    "though the bot said it should have",
                )
                logger.critical(
                    "Recipe did not change in version migration "
                    "but the code indicates an update was done!",
                )

        if did_update:
            with indir(recipe_dir):
                with open("meta.yaml", "w") as fp:
                    cmeta.dump(fp)
                self.set_build_number("meta.yaml")

            return super().migrate(recipe_dir, attrs)
        else:
            logger.critical("Recipe did not change in version migration!")
            attrs["new_version_errors"][version] = _fmt_error_message(errors, version)
            return {}

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

        # Display the url so that the maintainer can quickly click on it
        # in the PR body.
        about = feedstock_ctx.attrs.get("meta_yaml", {}).get("about", {})
        upstream_url = about.get("dev_url", "") or about.get("home", "")
        if upstream_url:
            upstream_url_link = ": see [upstream]({upstream_url})".format(
                upstream_url=upstream_url,
            )
        else:
            upstream_url_link = ""

        muid: dict
        body = body.format(
            "It is very likely that the current package version for this "
            "feedstock is out of date.\n"
            "Notes for merging this PR:\n"
            "1. Feel free to push to the bot's branch to update this PR if needed.\n"
            "2. The bot will almost always only open one PR per version.\n"
            "Checklist before merging this PR:\n"
            "- [ ] Dependencies have been updated if changed{upstream_url_link}\n"
            "- [ ] Tests have passed \n"
            "- [ ] Updated license if changed and `license_file` is packaged \n"
            "\n"
            "Note that the bot will stop issuing PRs if more than {max_num_prs} "
            "Version bump PRs "
            "generated by the bot are open. If you don't want to package a particular "
            "version please close the PR.\n\n"
            "**NEW: If you want these PRs to be merged automatically, make an issue "
            "with <code>@conda-forge-admin,</code>`please add bot automerge` in the "
            "title and merge the resulting PR. This command will add our new bot "
            "automerge feature to your feedstock!**\n\n"
            "{closes}".format(
                upstream_url_link=upstream_url_link,
                max_num_prs=self.max_num_prs,
                closes="\n".join(
                    [f"Closes: #{muid['number']}" for muid in open_version_prs],
                ),
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

        update_deps = (
            feedstock_ctx.attrs.get("conda-forge.yml", {})
            .get("bot", {})
            .get("inspection", "hint")
        )
        try:
            if update_deps == "hint":
                from conda_forge_tick.audit import (
                    extract_deps_from_source,
                    compare_depfinder_audit,
                )

                deps = extract_deps_from_source(
                    os.path.join(feedstock_ctx.feedstock_dir, "recipe"),
                )
                dep_comparison = compare_depfinder_audit(
                    deps,
                    feedstock_ctx.attrs,
                    feedstock_ctx.attrs["name"],
                    python_nodes=self.python_nodes,
                )
                hint = "\n\nDependency Analysis\n--------------------\n\n"
                hint += (
                    "Please note that this analysis is **highly experimental**. "
                    "The aim here is to make maintenance easier by inspecting the package's dependencies. "  # noqa: E501
                    "Importantly this analysis does not support optional dependencies, "
                    "please double check those before making changes. "
                    "If you do not want hinting of this kind ever please add "
                    "`bot: inspection: false` to your `conda-forge.yml`. "
                    "If you encounter issues with this feature please ping the bot team `conda-forge/bot`.\n\n"  # noqa: E501
                )
                if dep_comparison:
                    df_cf = ""
                    for k in dep_comparison.get("df_minus_cf", set()):
                        df_cf += f"- {k}" + "\n"
                    cf_df = ""
                    for k in dep_comparison.get("cf_minus_df", set()):
                        cf_df += f"- {k}" + "\n"
                    hint += (
                        "Analysis of the source code shows a discrepancy between"
                        " the library's imports and the package's stated requirements"
                        " in the meta.yaml."
                    )
                    if df_cf:
                        hint += (
                            "\n\n### Packages found by inspection but not in the meta.yaml:\n"  # noqa: E501
                            f"{df_cf}"
                        )
                    if cf_df:
                        hint += (
                            "\n\n### Packages found in the meta.yaml but not found by inspection:\n"  # noqa: E501
                            f"{cf_df}"
                        )
                else:
                    hint += (
                        "Analysis of the source code shows **no** discrepancy between"
                        " the library's imports and the package's stated requirements in the meta.yaml."  # noqa: E501
                    )
                body += hint
        except Exception:
            hint = "\n\nDependency Analysis\n--------------------\n\n"
            hint += (
                "We couldn't run dependency analysis due to an internal "
                "error in the bot. :( Help is very welcome!\n"
            )
            body += hint
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
            .get(
                "automerge",
                False,
            )
            in {"version", True}
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
        self,
        graph: nx.DiGraph,
        total_graph: nx.DiGraph,
    ) -> Sequence["PackageName"]:
        def _get_attemps_nr(node):
            with graph.nodes[node]["payload"] as attrs:
                new_version = attrs.get("new_version", "")
                attempts = attrs.get("new_version_attempts", {}).get(new_version, 0)
            return min(attempts, 3)

        def _get_attemps_r(node, seen):
            seen |= {node}
            attempts = _get_attemps_nr(node)
            for d in nx.descendants(graph, node):
                if d not in seen:
                    attempts = min(attempts, _get_attemps_r(d, seen))
            return attempts

        @functools.lru_cache(maxsize=1024)
        def _get_attemps(node):
            seen = set()
            return _get_attemps_r(node, seen)

        def _desc_cmp(node1, node2):
            if node1 in nx.descendants(graph, node2):
                return 1
            elif node2 in nx.descendants(graph, node1):
                return -1
            else:
                return 0

        random.seed()
        nodes_to_sort = list(graph.nodes)
        return sorted(
            sorted(
                sorted(nodes_to_sort, key=lambda x: random.uniform(0, 1)),
                key=_get_attemps,
            ),
            key=functools.cmp_to_key(_desc_cmp),
        )

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
        # make sure this is always a string
        return [str(attrs.get("branch", "main"))]
