import collections.abc
import hashlib
import io
import logging
import os
import pprint
import re
import shutil
import tempfile
import traceback
from pathlib import Path
from typing import Any, MutableMapping

import jinja2
import jinja2.sandbox
import orjson
import requests
from conda_forge_feedstock_ops.container_utils import (
    get_default_log_level_args,
    run_container_operation,
    should_use_container,
)
from conda_forge_feedstock_ops.os_utils import (
    chmod_plus_rwX,
    get_user_execute_permissions,
    reset_permissions_with_user_execute,
    sync_dirs,
)

from conda_forge_tick.hashing import hash_url
from conda_forge_tick.lazy_json_backends import loads
from conda_forge_tick.recipe_parser import CONDA_SELECTOR, CondaMetaYAML
from conda_forge_tick.settings import (
    ENV_CONDA_FORGE_ORG,
    ENV_GRAPH_GITHUB_BACKEND_REPO,
    settings,
)
from conda_forge_tick.url_transforms import gen_transformed_urls
from conda_forge_tick.utils import get_keys_default, sanitize_string

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
    selectors: list[None | str] = [None]
    for key in cmeta.jinja2_vars:
        if CONDA_SELECTOR in key:
            selectors.append(key.split(CONDA_SELECTOR)[1])
    for key in src:
        if CONDA_SELECTOR in key:
            selectors.append(key.split(CONDA_SELECTOR)[1])
    return set(selectors)


def _try_url_and_hash_it(url: str, hash_type: str) -> str | None:
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
    env = jinja2.sandbox.SandboxedEnvironment(undefined=jinja2.StrictUndefined)

    # We need to add the split filter to support v1 recipes
    def split_filter(value, sep):
        return value.split(sep)

    env.filters["split"] = split_filter

    return env.from_string(tmpl).render(**context)


def _try_pypi_api(url_tmpl: str, context: MutableMapping, hash_type: str, cmeta: Any):
    """
    Try to get a new version from the PyPI API. The returned URL might use a different
    format (host) than the original URL template, e.g. `https://files.pythonhosted.org/`
    instead of `https://pypi.io/`.

    Parameters
    ----------
    url_tmpl : str
        The URL template to try to update.
    context : dict
        The context to render the URL template.
    hash_type : str
        The hash type to use.

    Returns
    -------
    new_url_tmpl : str or None
        The new URL template if found.
    new_hash : str or None
        The new hash if found.
    """
    if "version" not in context:
        return None, None

    if not any(
        pypi_slug in url_tmpl
        for pypi_slug in ["/pypi.org/", "/pypi.io/", "/files.pythonhosted.org/"]
    ):
        return None, None

    orig_pypi_name = None

    # this is a v0 recipe
    if hasattr(cmeta, "meta"):
        orig_pypi_name_candidates = [
            url_tmpl.split("/")[-2],
            context.get("name", None),
            (cmeta.meta.get("package", {}) or {}).get("name", None),
        ]
        if "outputs" in cmeta.meta:
            for output in cmeta.meta["outputs"]:
                output = output or {}
                orig_pypi_name_candidates.append(output.get("name", None))
    else:
        # this is a v1 recipe
        orig_pypi_name_candidates = [
            url_tmpl.split("/")[-2],
            context.get("name", None),
            cmeta.get("package", {}).get("name", None),
        ]
        # for v1 recipe compatibility
        for output in cmeta.get("outputs", []):
            output = output or {}
            orig_pypi_name_candidates.append(
                get_keys_default(output, ["package", "name"], {}, None)
            )

    orig_pypi_name_candidates = sorted(
        {nc for nc in orig_pypi_name_candidates if nc is not None and len(nc) > 0},
        key=lambda x: len(x),
    )
    logger.info("PyPI name candidates: %s", orig_pypi_name_candidates)

    for _orig_pypi_name in orig_pypi_name_candidates:
        if _orig_pypi_name is None:
            continue

        if "{{ name }}" in _orig_pypi_name:
            _orig_pypi_name = _render_jinja2(_orig_pypi_name, context)

        try:
            r = requests.get(
                f"https://pypi.org/simple/{_orig_pypi_name}/",
                headers={"Accept": "application/vnd.pypi.simple.v1+json"},
            )
            r.raise_for_status()
        except Exception as e:
            logger.debug("PyPI API request failed: %s", repr(e), exc_info=e)
        else:
            orig_pypi_name = _orig_pypi_name
            break

    if orig_pypi_name is None or not r.ok:
        logger.error("PyPI name not found!")
        r.raise_for_status()

    logger.info("PyPI name: %s", orig_pypi_name)

    data = r.json()
    logger.debug("PyPI API data:\n%s", pprint.pformat(data))

    valid_src_exts = {".tar.gz", ".tar.bz2", ".tar.xz", ".zip", ".tgz"}
    finfo = None
    ext = None
    for _finfo in data["files"]:
        for valid_ext in valid_src_exts:
            if _finfo["filename"].endswith(context["version"] + valid_ext):
                ext = valid_ext
                finfo = _finfo
                break

    if finfo is None or ext is None:
        logger.error(
            "src dist for version %s not found in PyPI API for name %s",
            context["version"],
            orig_pypi_name,
        )
        return None, None

    bn, _ = os.path.split(url_tmpl)
    pypi_name = finfo["filename"].split(context["version"] + ext)[0]
    logger.debug("PyPI API file name: %s", pypi_name)
    name_tmpl = None
    if "name" in context:
        for tmpl in [
            "{{ name }}",
            "{{ name | lower }}",
            "{{ name | replace('-', '_') }}",
            "{{ name | replace('_', '-') }}",
            "{{ name | replace('-', '_') | lower }}",
            "{{ name | replace('_', '-') | lower }}",
        ]:
            if pypi_name == _render_jinja2(tmpl, context) + "-":
                name_tmpl = tmpl
                break

    if name_tmpl is not None:
        new_url_tmpl = os.path.join(bn, name_tmpl + "-" + "{{ version }}" + ext)
    else:
        new_url_tmpl = os.path.join(
            bn, finfo["filename"].replace(context["version"], "{{ version }}")
        )

    logger.debug("new url template from PyPI API: %s", new_url_tmpl)
    url = _render_jinja2(new_url_tmpl, context)
    new_hash = _try_url_and_hash_it(url, hash_type)
    if new_hash is not None:
        return new_url_tmpl, new_hash

    new_url_tmpl = finfo["url"].replace(context["version"], "{{ version }}")
    logger.debug("new url template from PyPI API: %s", new_url_tmpl)
    url = _render_jinja2(new_url_tmpl, context)
    new_hash = _try_url_and_hash_it(url, hash_type)
    if new_hash is not None:
        return new_url_tmpl, new_hash

    return None, None


def _get_new_url_tmpl_and_hash(
    url_tmpl: str, context: MutableMapping, hash_type: str, cmeta: Any
):
    logger.info(
        "processing URL template: %s",
        url_tmpl,
    )
    if context:
        logger.info("rendering URL w/ jinja2 context: %s", pprint.pformat(context))

    try:
        url = _render_jinja2(url_tmpl, context)
        logger.info("initial rendered URL: %s", url)
    except jinja2.UndefinedError:
        logger.info("initial URL template does not render")
        url = None
        pass

    if url != url_tmpl:
        new_hash = _try_url_and_hash_it(url, hash_type)
        if new_hash is not None:
            return url_tmpl, new_hash
    else:
        logger.info("initial URL template does not update with version. skipping it.")

    new_url_tmpl = None
    new_hash = None

    try:
        new_url_tmpl, new_hash = _try_pypi_api(url_tmpl, context, hash_type, cmeta)
        if new_hash is not None and new_url_tmpl is not None:
            return new_url_tmpl, new_hash
    except Exception as e:
        logger.debug("PyPI API url+hash update failed: %s", repr(e), exc_info=e)

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


def _try_to_update_version(cmeta: Any, src, hash_type: str):
    errors: set[str] = set()

    local_vals = ["path", "folder"]
    if all(any(lval in k for lval in local_vals) for k in src):
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
                    cmeta,
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
                cmeta,
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


def update_version_feedstock_dir(
    feedstock_dir, version, hash_type="sha256", use_container=None
):
    """Update the version in a recipe.

    Parameters
    ----------
    feedstock_dir : str
        The feedstock directory w/ the recipe to update.
    version : str
        The version of the recipe.
    hash_type : str, optional
        The kind of hash used on the source. Default is sha256.
    use_container : bool, optional
        Whether to use a container to run the version parsing.
        If None, the function will use a container if the environment
        variable `CF_FEEDSTOCK_OPS_IN_CONTAINER` is 'false'. This feature can be
        used to avoid container in container calls.

    Returns
    -------
    updated : bool
        If the recipe was updated, True, otherwise False.
    errors : str of str
        A set of strings giving any errors found when updating the
        version. The set will be empty if there were no errors.
    """
    if should_use_container(use_container=use_container):
        return _update_version_feedstock_dir_containerized(
            feedstock_dir,
            version,
            hash_type,
        )
    else:
        return _update_version_feedstock_dir_local(
            feedstock_dir,
            version,
            hash_type,
        )


def _update_version_feedstock_dir_local(
    feedstock_dir, version, hash_type
) -> tuple[bool, set]:
    feedstock_path = Path(feedstock_dir)

    recipe_path = None
    recipe_path_v0 = feedstock_path / "recipe" / "meta.yaml"
    recipe_path_v1 = feedstock_path / "recipe" / "recipe.yaml"
    updated_meta_yaml: str | None
    if recipe_path_v0.exists():
        recipe_path = recipe_path_v0
        updated_meta_yaml, errors = update_version(
            recipe_path_v0.read_text(), version, hash_type=hash_type
        )
    elif recipe_path_v1.exists():
        recipe_path = recipe_path_v1
        updated_meta_yaml, errors = update_version_v1(feedstock_dir, version, hash_type)
    else:
        return False, {"no recipe found"}

    if updated_meta_yaml is not None:
        recipe_path.write_text(updated_meta_yaml)

    return updated_meta_yaml is not None, errors


def _update_version_feedstock_dir_containerized(feedstock_dir, version, hash_type):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_feedstock_dir = os.path.join(tmpdir, os.path.basename(feedstock_dir))
        sync_dirs(
            feedstock_dir, tmp_feedstock_dir, ignore_dot_git=True, update_git=False
        )

        perms = get_user_execute_permissions(feedstock_dir)
        with open(
            os.path.join(tmpdir, f"permissions-{os.path.basename(feedstock_dir)}.json"),
            "wb",
        ) as f:
            f.write(orjson.dumps(perms))

        chmod_plus_rwX(tmpdir, recursive=True)

        logger.debug(
            "host feedstock dir %s: %s", feedstock_dir, os.listdir(feedstock_dir)
        )
        logger.debug(
            "copied host feedstock dir %s: %s",
            tmp_feedstock_dir,
            os.listdir(tmp_feedstock_dir),
        )

        args = [
            "conda-forge-tick-container",
            "update-version",
            "--version",
            version,
            "--hash-type",
            hash_type,
        ]
        args += get_default_log_level_args(logger)

        data = run_container_operation(
            args,
            mount_readonly=False,
            mount_dir=tmpdir,
            json_loads=loads,
            extra_container_args=[
                "-e",
                f"{ENV_CONDA_FORGE_ORG}={settings().conda_forge_org}",
                "-e",
                f"{ENV_GRAPH_GITHUB_BACKEND_REPO}={settings().graph_github_backend_repo}",
            ],
        )

        sync_dirs(
            tmp_feedstock_dir,
            feedstock_dir,
            ignore_dot_git=True,
            update_git=False,
        )
        reset_permissions_with_user_execute(feedstock_dir, data["permissions"])

        # When tempfile removes tempdir, it tries to reset permissions on subdirs.
        # This causes a permission error since the subdirs were made by the user
        # in the container. So we remove the subdir we made before cleaning up.
        shutil.rmtree(tmp_feedstock_dir)

    data.pop("permissions", None)
    return data["updated"], data["errors"]


def update_version_v1(
    feedstock_dir: str, version: str, hash_type: str
) -> tuple[str | None, set[str]]:
    """Update the version in a recipe.

    Parameters
    ----------
    feedstock_dir : str
        The feedstock directory to update.
    version : str
        The new version of the recipe.
    hash_type : str
        The kind of hash used on the source.

    Returns
    -------
    recipe_text : str or None
        The text of the updated recipe.yaml. Will be None if there is an error.
    errors : set of str
    """
    # extract all the URL sources from a given recipe / feedstock directory
    from rattler_build_conda_compat.loader import load_yaml
    from rattler_build_conda_compat.recipe_sources import render_all_sources

    updated_version = True
    errors = set()

    feedstock_dir = Path(feedstock_dir)
    recipe_path = feedstock_dir / "recipe" / "recipe.yaml"
    recipe_text = recipe_path.read_text()
    recipe_yaml = load_yaml(recipe_text)
    variants = feedstock_dir.glob(".ci_support/*.yaml")
    # load all variants
    variants = [load_yaml(variant.read_text()) for variant in variants]
    if not len(variants):
        # if there are no variants, then we need to add an empty one
        variants = [{}]

    rendered_sources = render_all_sources(
        recipe_yaml, variants, override_version=version
    )
    if not rendered_sources:
        errors.add("no source sections were found in the rendered recipe")
        return None, errors

    # mangle the version if it is R
    for source in rendered_sources:
        if isinstance(source.template, list):
            if any([_is_r_url(t) for t in source.template]):
                version = version.replace("_", "-")
        else:
            if _is_r_url(source.template):
                version = version.replace("_", "-")

    # update the version with a regex replace
    updated_version_via_regex = False
    for line in recipe_text.splitlines():
        if match := re.match(r"^(\s+)version:\s.*$", line):
            indentation = match.group(1)
            recipe_text = recipe_text.replace(
                line, f'{indentation}version: "{version}"'
            )
            updated_version_via_regex = True
            break

    if not updated_version_via_regex:
        errors.add(
            f"could not update `version` key in `context` section in recipe.yaml to '{version}'"
        )
        return None, errors

    updated_version = True
    for source in rendered_sources:
        # update the hash value
        urls = source.url
        # zip url and template
        if not isinstance(urls, list):
            urls = zip([urls], [source.template])
        else:
            urls = zip(urls, source.template)

        new_hash = None
        for url, template in urls:
            if source.sha256 is not None:
                hash_type = "sha256"
            elif source.md5 is not None:
                hash_type = "md5"

            # convert to regular jinja2 template
            cb_template = template.replace("${{", "{{")
            new_tmpl, new_hash = _get_new_url_tmpl_and_hash(
                cb_template,
                source.context,
                hash_type,
                recipe_yaml,
            )

            if new_hash is not None:
                logger.info("new URL template: %s", new_tmpl)
                logger.info("new URL hash: %s", new_hash)

                if hash_type == "sha256":
                    recipe_text = recipe_text.replace(source.sha256, new_hash)
                else:
                    recipe_text = recipe_text.replace(source.md5, new_hash)

                # convert back to v1 minijinja template
                new_tmpl = new_tmpl.replace("{{", "${{")
                if new_tmpl != template:
                    recipe_text = recipe_text.replace(template, new_tmpl)

                break
            else:
                errors.add("could not hash URL template '%s'" % cb_template)

        updated_version &= new_hash is not None

    logger.info("updated|errors: %r|%r", updated_version, errors)

    if not updated_version:
        return None, errors
    else:
        return recipe_text, set()


def update_version(
    raw_meta_yaml, version, hash_type="sha256"
) -> tuple[str | None, set[str]]:
    """Update the version in a v0 recipe.

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
