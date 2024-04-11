import collections.abc
import hashlib
import io
import logging
import pprint
import re
import traceback
from typing import Any, MutableMapping

import jinja2
import jinja2.sandbox

from conda_forge_tick.hashing import hash_url
from conda_forge_tick.recipe_parser import CONDA_SELECTOR, CondaMetaYAML
from conda_forge_tick.url_transforms import gen_transformed_urls
from conda_forge_tick.utils import sanitize_string

CHECKSUM_NAMES = [
    "hash_value",
    "hash",
    "hash_val",
    "sha256sum",
    "checksum",
]

# matches valid jinja2 vars
JINJA2_VAR_RE = re.compile("{{ ((?:[a-zA-Z]|(?:_[a-zA-Z0-9]))[a-zA-Z0-9_]*) }}")

logger = logging.getLogger(__name__)


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
    return (
        jinja2.sandbox.SandboxedEnvironment(undefined=jinja2.StrictUndefined)
        .from_string(tmpl)
        .render(**context)
    )


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
        # this pulls out any jinja2 expressions that are not constants
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
                        "missing jinja2 variable '{}' for selector '{}'".format(
                            var, selector
                        ),
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

    logger.info("updated|errors: %r|%r", updated_version, errors)

    return updated_version, errors


def update_version(raw_meta_yaml, version, hash_type="sha256"):
    """Update the version in a recipe.

    Parameters
    ----------
    raw_meta_yaml : str
        The recipe meta.yaml as a string.
    version : str
        The version of the recipe.
    hash_type : str, optional
        The kind of hash used on the source. Default is sha256.

    Returns
    -------
    updated_meta_yaml : str or None
        The updated meta.yaml. Will be None if there is an error.
    errors : str of str
        A set of strings giving any errors found when updating the
        version. The set will be empty if there were no errors.
    """
    errors = set()

    if not isinstance(version, str):
        errors.add(
            "the version '%s' is not a string and must be for the bot" % version,
        )
        logger.critical(
            "the version '%s' is not a string and must be for the bot",
            version,
        )
        return None, errors

    try:
        cmeta = CondaMetaYAML(raw_meta_yaml)
    except Exception as e:
        tb = io.StringIO()
        traceback.print_tb(e.__traceback__, file=tb)
        tb.seek(0)
        tb = tb.read()
        errors.add(
            sanitize_string(
                "We found a problem parsing the recipe for version '"
                + version
                + "': \n\n"
                + repr(e)
                + "\n\ntraceback:\n"
                + tb,
            ),
        )
        logger.critical(
            "We found a problem parsing the recipe: \n\n%s\n\n%s",
            sanitize_string(str(e)),
            sanitize_string(tb),
        )
        return None, errors

    # cache round-tripped yaml for testing later
    s = io.StringIO()
    cmeta.dump(s)
    s.seek(0)
    old_meta_yaml = s.read()

    # if is a git url, then we error
    if _recipe_has_git_url(cmeta) and not _recipe_has_url(cmeta):
        logger.critical("Migrations do not work on `git_url`s!")
        errors.add("migrations do not work on `git_url`s")
        return None, errors

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
        return None, errors

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
        s = io.StringIO()
        cmeta.dump(s)
        s.seek(0)
        updated_meta_yaml = s.read()
        return updated_meta_yaml, set()
    else:
        logger.critical("Recipe did not change in version migration!")
        return None, errors
