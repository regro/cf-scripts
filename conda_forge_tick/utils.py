import contextlib
import copy
import datetime
import io
import itertools
import logging
import os
import pprint
import re
import subprocess
import sys
import tempfile
import time
import traceback
import typing
import warnings
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    MutableMapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    cast,
)

import dateparser
import jinja2
import jinja2.sandbox
import networkx as nx
import orjson
import ruamel.yaml
from conda.models.version import VersionOrder
from conda_forge_feedstock_ops.container_utils import (
    get_default_log_level_args,
    run_container_operation,
    should_use_container,
)

from . import sensitive_env
from .lazy_json_backends import LazyJson
from .recipe_parser import CondaMetaYAML
from .settings import ENV_CONDA_FORGE_ORG, ENV_GRAPH_GITHUB_BACKEND_REPO, settings

if typing.TYPE_CHECKING:
    from mypy_extensions import TypedDict

from conda_forge_tick.migrators_types import RecipeTypedDict

logger = logging.getLogger(__name__)

T = typing.TypeVar("T")
TD = typing.TypeVar("TD", bound=dict, covariant=True)

PACKAGE_STUBS = [
    "_compiler_stub",
    "_stdlib_stub",
    "subpackage_stub",
    "compatible_pin_stub",
    "cdt_stub",
]


class MockOS:
    def __init__(self):
        self.environ = defaultdict(str)
        self.sep = "/"


CB_CONFIG = dict(
    os=MockOS(),
    environ=defaultdict(str),
    compiler=lambda x: x + "_compiler_stub",
    stdlib=lambda x: x + "_stdlib_stub",
    pin_subpackage=lambda *args, **kwargs: args[0],
    pin_compatible=lambda *args, **kwargs: args[0],
    cdt=lambda *args, **kwargs: "cdt_stub",
    cran_mirror="https://cran.r-project.org",
    datetime=datetime,
    load_file_regex=lambda *args, **kwargs: None,
)


def _munge_dict_repr(dct: Dict[Any, Any]) -> str:
    from urllib.parse import quote_plus

    return "__quote_plus__" + quote_plus(repr(dct)) + "__quote_plus__"


CB_CONFIG_PINNING = dict(
    os=MockOS(),
    environ=defaultdict(str),
    compiler=lambda x: x + "_compiler_stub",
    stdlib=lambda x: x + "_stdlib_stub",
    # The `max_pin, ` stub is so we know when people used the functions
    # to create the pins
    pin_subpackage=lambda *args, **kwargs: _munge_dict_repr(
        {"package_name": args[0], **kwargs},
    ),
    pin_compatible=lambda *args, **kwargs: _munge_dict_repr(
        {"package_name": args[0], **kwargs},
    ),
    cdt=lambda *args, **kwargs: "cdt_stub",
    cran_mirror="https://cran.r-project.org",
    datetime=datetime,
    load_file_regex=lambda *args, **kwargs: None,
)

DEFAULT_GRAPH_FILENAME = "graph.json"

DEFAULT_CONTAINER_TMPFS_SIZE_MB = 6000


def parse_munged_run_export(p: str) -> Dict:
    from urllib.parse import unquote_plus

    # get rid of comments
    p = p.split("#")[0].strip()

    # remove build string
    p = p.rsplit("__quote_plus__", maxsplit=1)[0].strip()

    # unquote
    if p.startswith("__quote_plus__") or p.endswith("__quote_plus__"):
        if p.startswith("__quote_plus__"):
            p = p[len("__quote_plus__") :]
        if p.endswith("__quote_plus__"):
            p = p[: -len("__quote_plus__")]
        p = unquote_plus(p)

    return cast(Dict, yaml_safe_load(p))


REPRINTED_LINES = {}


@contextlib.contextmanager
def filter_reprinted_lines(key):
    global REPRINTED_LINES
    if key not in REPRINTED_LINES:
        REPRINTED_LINES[key] = set()

    stdout = io.StringIO()
    stderr = io.StringIO()

    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            yield
    finally:
        for line in stdout.getvalue().split("\n"):
            if line not in REPRINTED_LINES[key]:
                print(line, file=sys.stdout)
                REPRINTED_LINES[key].add(line)
        for line in stderr.getvalue().split("\n"):
            if line not in REPRINTED_LINES[key]:
                print(line, file=sys.stderr)
                REPRINTED_LINES[key].add(line)


LOG_LINES_FOLDED = False


@contextlib.contextmanager
def fold_log_lines(title):
    global LOG_LINES_FOLDED
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        if os.environ.get("GITHUB_ACTIONS", "false") == "true" and not LOG_LINES_FOLDED:
            LOG_LINES_FOLDED = True
            print(f"::group::{title}", flush=True)
        else:
            print(">" * 80, flush=True)
            print(">" * 80, flush=True)
            print("> " + title, flush=True)
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        if os.environ.get("GITHUB_ACTIONS", "false") == "true":
            LOG_LINES_FOLDED = False
            print("::endgroup::", flush=True)


def yaml_safe_load(stream):
    """Load a yaml doc safely."""
    return ruamel.yaml.YAML(typ="safe", pure=True).load(stream)


def yaml_safe_dump(data, stream=None):
    """Dump a yaml object."""
    yaml = ruamel.yaml.YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
    return yaml.dump(data, stream=stream)


def _render_meta_yaml(text: str, for_pinning: bool = False, **kwargs) -> str:
    """Render the meta.yaml with Jinja2 variables.

    Parameters
    ----------
    text : str
        The raw text in conda-forge feedstock meta.yaml file

    Returns
    -------
    str
        The text of the meta.yaml with Jinja2 variables replaced.

    """
    cfg = dict(**kwargs)

    env = jinja2.sandbox.SandboxedEnvironment(undefined=NullUndefined)
    if for_pinning:
        cfg.update(**CB_CONFIG_PINNING)
    else:
        cfg.update(**CB_CONFIG)

    try:
        return env.from_string(text).render(**cfg)
    except Exception:
        import traceback

        logger.debug("render failure:\n%s", traceback.format_exc())
        logger.debug("render template: %s", text)
        logger.debug("render context:\n%s", pprint.pformat(cfg))
        raise


def parse_recipe_yaml(
    text: str,
    for_pinning: bool = False,
    platform_arch: str | None = None,
    cbc_path: Path | str | None = None,
    use_container: bool | None = None,
) -> "RecipeTypedDict":
    """Parse the recipe.yaml.

    Parameters
    ----------
    text : str
        The raw text in conda-forge feedstock recipe.yaml file
    for_pinning : bool, optional
        If True, render the recipe.yaml for pinning migrators, by default False.
    platform_arch : str, optional
        The platform and arch (e.g., 'linux-64', 'osx-arm64', 'win-64').
    cbc_path : Path | str, optional
        The value of or path to global pinning file.
    use_container
        Whether to use a container to run the parsing.
        If None, the function will use a container if the environment
        variable `CF_FEEDSTOCK_OPS_IN_CONTAINER` is 'false'. This feature can be
        used to avoid container in container calls.

    Returns
    -------
    dict :
        The parsed YAML dict. If parsing fails, returns an empty dict. May raise
        for some errors. Have fun.
    """
    if should_use_container(use_container=use_container):
        return parse_recipe_yaml_containerized(
            text,
            for_pinning=for_pinning,
            platform_arch=platform_arch,
            cbc_path=cbc_path,
        )
    else:
        return parse_recipe_yaml_local(
            text,
            for_pinning=for_pinning,
            platform_arch=platform_arch,
            cbc_path=cbc_path,
        )


def parse_recipe_yaml_containerized(
    text: str,
    for_pinning: bool = False,
    platform_arch: str | None = None,
    cbc_path: Path | str | None = None,
) -> "RecipeTypedDict":
    """Parse the recipe.yaml.

    **This function runs the parsing in a container.**

    Parameters
    ----------
    text : str
        The raw text in conda-forge feedstock recipe.yaml file
    for_pinning : bool, optional
        If True, render the recipe.yaml for pinning migrators, by default False.
    platform_arch : str, optional
        The platform and arch (e.g., 'linux-64', 'osx-arm64', 'win-64').
    cbc_path : Path | str, optional
        The value of or path to global pinning file.

    Returns
    -------
    dict :
        The parsed YAML dict. If parsing fails, returns an empty dict. May raise
        for some errors. Have fun.
    """

    def _run(_args, _mount_dir):
        return run_container_operation(
            _args,
            input=text,
            mount_readonly=True,
            mount_dir=_mount_dir,
            extra_container_args=[
                "-e",
                f"{ENV_CONDA_FORGE_ORG}={settings().conda_forge_org}",
                "-e",
                f"{ENV_GRAPH_GITHUB_BACKEND_REPO}={settings().graph_github_backend_repo}",
            ],
        )

    args = [
        "conda-forge-tick-container",
        "parse-recipe-yaml",
    ]

    args += get_default_log_level_args(logger)

    if platform_arch is not None:
        args += ["--platform-arch", platform_arch]

    if for_pinning:
        args += ["--for-pinning"]

    if cbc_path is not None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chmod(tmpdir, 0o755)

            tmp_cbc_path = os.path.join(tmpdir, "cbc_path.yaml")
            if os.path.exists(cbc_path):
                with open(cbc_path) as fp_r:
                    cbc_data = fp_r.read()
            else:
                cbc_data = cbc_path

            with open(tmp_cbc_path, "w") as fp:
                fp.write(cbc_data)

            args += ["--cbc-path", "/cf_feedstock_ops_dir/cbc_path.yaml"]

            data = _run(args, tmpdir)
    else:
        data = _run(args, None)

    return data


def _flatten_requirement_pin_dicts(
    recipes: list["RecipeTypedDict"],
) -> list["RecipeTypedDict"]:
    """
    Flatten out any "pin" dictionaries.

    The `${{ pin_subpackage(foo) }}` and `${{ pin_compatible(foo) }}` functions
    are converted into dictionaries. However, we want to extract the name only.
    """

    def flatten_pin(s: str | Mapping[str, Any]) -> str:
        if isinstance(s, Mapping):
            if "pin_subpackage" in s:
                return s["pin_subpackage"]["name"]
            elif "pin_compatible" in s:
                return s["pin_compatible"]["name"]
            raise ValueError(f"Unknown pinning dict: {s}")
        return s

    def flatten_requirement_list(list: Sequence[str | Mapping[str, Any]]) -> list[str]:
        return [flatten_pin(s) for s in list]

    def flatten_requirements(output: MutableMapping[str, Any]) -> dict[str, Any]:
        if "requirements" in output:
            requirements = output["requirements"]
            for key in ["build", "host", "run"]:
                if key in requirements:
                    requirements[key] = flatten_requirement_list(requirements[key])
            if "run_exports" in requirements:
                if isinstance(requirements["run_exports"], list):
                    requirements["run_exports"] = flatten_requirement_list(
                        requirements["run_exports"]
                    )
                else:
                    for key in requirements["run_exports"]:
                        requirements["run_exports"][key] = flatten_requirement_list(
                            requirements["run_exports"][key]
                        )

    for recipe in recipes:
        if "requirements" in recipe:
            flatten_requirements(recipe)

        if "outputs" in recipe:
            for output in recipe["outputs"]:
                flatten_requirements(output)

        if "tests" in recipe:
            # script tests can have `run` and `build` requirements
            for test in recipe["tests"]:
                if "requirements" in test:
                    flatten_requirements(test)

    return recipes


def parse_recipe_yaml_local(
    text: str,
    for_pinning: bool = False,
    platform_arch: str | None = None,
    cbc_path: Path | str | None = None,
) -> "RecipeTypedDict":
    """Parse the recipe.yaml.

    Parameters
    ----------
    text : str
        The raw text in conda-forge feedstock recipe.yaml file
    for_pinning : bool, optional
        If True, render the recipe.yaml for pinning migrators, by default False.
    platform_arch : str, optional
        The platform and arch (e.g., 'linux-64', 'osx-arm64', 'win-64').
    cbc_path : Path | str, optional
        The value of or path to global pinning file.

    Returns
    -------
    dict :
        The parsed YAML dict. If parsing fails, returns an empty dict. May raise
        for some errors. Have fun.

    Raises
    ------
    RuntimeError
        If the recipe YAML rendering fails or no output recipes are found.
    """
    rendered_recipes = _render_recipe_yaml(
        text, cbc_path=cbc_path, platform_arch=platform_arch
    )
    if not rendered_recipes:
        raise RuntimeError("Failed to render recipe YAML! No output recipes found!")

    if for_pinning:
        rendered_recipes = _process_recipe_for_pinning(rendered_recipes)
    else:
        rendered_recipes = _flatten_requirement_pin_dicts(rendered_recipes)
    parsed_recipes = _parse_recipes(rendered_recipes)
    return parsed_recipes


def replace_compiler_with_stub(text: str) -> str:
    """
    Replace compiler function calls with a stub function call to match the conda-build
    output.

    Parameters
    ----------
    text : str

    Returns
    -------
    str
    """
    pattern = r'\$\{\{\s*compiler\((["\'])(.*?)\1\)\s*\}\}'
    text = re.sub(pattern, lambda m: f"{m.group(2)}_compiler_stub", text)

    pattern = r'\$\{\{\s*stdlib\((["\'])(.*?)\1\)\s*\}\}'
    text = re.sub(pattern, lambda m: f"{m.group(2)}_stdlib_stub", text)

    return text


def _render_recipe_yaml(
    text: str,
    platform_arch: str | None = None,
    cbc_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Render the given recipe YAML text using the `rattler-build` command-line tool.

    Parameters
    ----------
    text : str
        The recipe YAML text to render.
    platform_arch : str, optional
        The platform-arch (e.g., 'linux-64').
    cbc_path : str | Path, optional
        The value of or path to global pinning file.

    Returns
    -------
    dict[str, Any]
        The rendered recipe as a dictionary.

    Raises
    ------
    RuntimeError
        If no output recipes are found.
    """
    if cbc_path is not None and not os.path.exists(str(cbc_path)):
        ctx = tempfile.TemporaryDirectory
    else:
        ctx = contextlib.nullcontext

    with ctx() as tmpdir:
        if cbc_path is not None and not os.path.exists(str(cbc_path)):
            _cbc_path = os.path.join(tmpdir, "conda_build_config.yaml")
            with open(_cbc_path, "w") as fp:
                fp.write(cbc_path)

            variant_config_flags = ["--variant-config", _cbc_path]
        else:
            variant_config_flags = (
                [] if cbc_path is None else ["--variant-config", str(cbc_path)]
            )
        target_platform_flags = (
            []
            if platform_arch is None or variant_config_flags
            else ["--target-platform", platform_arch]
        )

        prepared_text = replace_compiler_with_stub(text)

        res = subprocess.run(
            ["rattler-build", "build", "--render-only"]
            + variant_config_flags
            + target_platform_flags,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            input=prepared_text,
            check=False,
        )
        if res.stdout:
            outputs = [output["recipe"] for output in orjson.loads(res.stdout)]
        else:
            outputs = []

        if res.returncode != 0 or len(outputs) == 0:
            logger.critical(
                "error parsing recipe.yaml:\n%s\n%s", res.stdout, res.stderr
            )
            res.check_returncode()

        if len(outputs) == 0:
            raise RuntimeError(
                f"Failed to render recipe YAML! No output recipes found!\n{res.stdout}\n{res.stderr}"
            )
        return outputs


def _process_recipe_for_pinning(recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def replace_name_key(d: dict[str, Any]) -> Any:
        for key, value in d.items():
            if isinstance(value, dict):
                if key in ["pin_subpackage", "pin_compatible"] and "name" in value:
                    # Create a new dictionary with 'package_name' first
                    new_value = {"package_name": value.pop("name")}
                    new_value.update(value)
                    d[key] = {"name": _munge_dict_repr(new_value)}
                else:
                    replace_name_key(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        replace_name_key(item)
        return d

    return [replace_name_key(recipe) for recipe in recipes]


def _parse_recipes(
    validated_recipes: list[dict[str, Any]],
) -> "RecipeTypedDict":
    """Parse validated recipes and transform them to fit `RecipeTypedDict`.

    Parameters
    ----------
    validated_recipes : list[dict[str, Any]]
        The recipes validated and rendered by `rattler-build`

    Returns
    -------
    RecipeTypedDict
        A dict conforming to conda-build's rendered output
    """
    # some heuristics to find the "top-level" name and version
    # we use these in the following order
    # 1. Does the output name match the "name" field in the context block
    #    if present?
    # 2. Does the output version match the "version" field in the
    #    context block if present?
    # 3. Does the output name match the feedstock-name in the extra
    #    field if present?
    if len(validated_recipes) > 1:
        if "name" in validated_recipes[0].get("context", {}):
            sval = validated_recipes[0]["context"]["name"]
            skey = "name"
        elif "version" in validated_recipes[0].get("context", {}):
            sval = str(validated_recipes[0]["context"]["version"])
            skey = "version"
        elif "feedstock-name" in validated_recipes[0].get("extra", {}):
            sval = validated_recipes[0]["extra"]["feedstock-name"]
            skey = "name"
        else:
            sval = None
            skey = None

        if sval is not None and skey is not None:
            sind = None
            for ind, recipe in enumerate(validated_recipes):
                if recipe.get("package", {}).get(skey, "") == sval:
                    sind = ind
                    break
            if sind is not None:
                first = validated_recipes.pop(sind)
                validated_recipes = [first] + validated_recipes

    first = validated_recipes[0]
    about = first["about"]
    build = first["build"]
    requirements = first["requirements"]
    package = first["package"]
    source = first.get("source")

    about_data = (
        None
        if about is None
        else {
            "description": about.get("description"),
            "dev_url": about.get("repository"),
            "doc_url": about.get("documentation"),
            "home": about.get("homepage"),
            "license": about.get("license"),
            "license_family": about.get("license"),
            "license_file": about.get("license_file", [None])[0],
            "summary": about.get("summary"),
        }
    )

    _parse_recipe_yaml_requirements(requirements)

    build_data = (
        None
        if build is None or requirements is None
        else {
            "noarch": build.get("noarch"),
            "number": str(build.get("number")),
            "script": build.get("script"),
            "run_exports": requirements.get("run_exports"),
        }
    )
    package_data = (
        None
        if package is None
        else {"name": package.get("name"), "version": package.get("version")}
    )
    if isinstance(source, list) and len(source) > 0:
        source_data = {
            "fn": source[0].get("file_name"),
            "patches": source[0].get("patches"),
            "sha256": source[0].get("sha256"),
            "url": source[0].get("url"),
            "git_url": source[0].get("git"),
            "git_rev": source[0].get("tag"),
        }

    requirements_data = (
        None
        if requirements is None
        else {
            "build": requirements.get("build"),
            "host": requirements.get("host"),
            "run": requirements.get("run"),
        }
    )
    output_data = []
    for recipe in validated_recipes:
        package_output = recipe.get("package")
        requirements_output = recipe.get("requirements")

        run_exports_output = (
            None
            if requirements_output is None
            else requirements_output.get("run_exports")
        )
        requirements_output_data = (
            None
            if requirements_output is None
            else {
                "build": requirements_output.get("build", []),
                "host": requirements_output.get("host", []),
                "run": requirements_output.get("run", []),
            }
        )
        build_output_data = (
            None
            if run_exports_output is None
            else {
                "strong": run_exports_output.get("strong", []),
                "weak": run_exports_output.get("weak", []),
            }
        )
        output_data.append(
            {
                "name": None if package_output is None else package_output.get("name"),
                "version": None
                if package_output is None
                else package_output.get("version"),
                "requirements": requirements_output_data,
                "build": build_output_data,
                "tests": recipe.get("tests", []),
            }
        )

    parsed_recipes = {
        "about": about_data,
        "build": build_data,
        "package": package_data,
        "requirements": requirements_data,
        "source": source_data,
        "outputs": output_data,
        "extra": first.get("extra"),
    }

    return _remove_none_values(parsed_recipes)


def _parse_recipe_yaml_requirements(requirements) -> None:
    """Parse requirement section of render by rattler-build to fit `RecipeTypedDict`.

    When rendering the recipe by rattler build,
    `requirements["run_exports"]["weak"]` gives a list looking like:
    [
        {
          "pin_subpackage": {
            "name": "slepc",
            "lower_bound": "x.x.x.x.x.x",
            "upper_bound": "x.x"
          }
        },
        "numpy"
    ]
    `run_exports["weak"]` of RecipeTypedDict looks like:
    [
        "slepc",
        "numpy"
    ]

    The same applies to "strong".

    This function takes care of this transformation

        requirements : dict
        The requirements section of the recipe rendered by rattler-build.
        This parameter will be modified by this function.
    """
    if "run_exports" not in requirements:
        return

    run_exports = requirements["run_exports"]
    for strength in ["strong", "weak"]:
        original = run_exports.get(strength)
        if isinstance(original, list):
            result = []
            for entry in original:
                if isinstance(entry, str):
                    result.append(entry)
                elif isinstance(entry, dict):
                    for key in ["pin_subpackage", "pin_compatible"]:
                        if key in entry and "name" in entry[key]:
                            result.append(entry[key]["name"])
            run_exports[strength] = result


def _remove_none_values(d):
    """Recursively remove dictionary entries with None values."""
    if not isinstance(d, dict):
        return d
    return {k: _remove_none_values(v) for k, v in d.items() if v is not None}


def get_recipe_schema_version(feedstock_attrs: Mapping[str, Any]) -> int:
    """
    Get the recipe schema version from the feedstock attributes.

    Parameters
    ----------
    feedstock_attrs : Mapping[str, Any]
        The feedstock attributes.

    Returns
    -------
    int
        The recipe version. If it does not exist in the feedstock attributes,
        it defaults to 0.

    Raises
    ------
    ValueError
        If the recipe version is not an integer, i.e. the attributes are invalid.
    """
    version = get_keys_default(
        feedstock_attrs,
        ["meta_yaml", "schema_version"],
        {},
        0,
    )

    if not isinstance(version, int):
        raise ValueError("Recipe version is not an integer")

    return version


def parse_meta_yaml(
    text: str,
    for_pinning=False,
    platform=None,
    arch=None,
    cbc_path=None,
    orig_cbc_path=None,
    log_debug=False,
    use_container: bool | None = None,
) -> "RecipeTypedDict":
    """Parse the meta.yaml.

    Parameters
    ----------
    text : str
        The raw text in conda-forge feedstock meta.yaml file
    for_pinning : bool, optional
        If True, render the meta.yaml for pinning migrators, by default False.
    platform : str, optional
        The platform (e.g., 'linux', 'osx', 'win').
    arch : str, optional
        The CPU architecture (e.g., '64', 'aarch64').
    cbc_path : str, optional
        The path to global pinning file.
    orig_cbc_path : str, optional
        If not None, the original conda build config file to put next to
        the recipe while parsing.
    log_debug : bool, optional
        If True, print extra debugging info. Default is False.
    use_container
        Whether to use a container to run the parsing.
        If None, the function will use a container if the environment
        variable `CF_FEEDSTOCK_OPS_IN_CONTAINER` is 'false'. This feature can be
        used to avoid container in container calls.

    Returns
    -------
    dict :
        The parsed YAML dict. If parsing fails, returns an empty dict. May raise
        for some errors. Have fun.
    """
    if should_use_container(use_container=use_container):
        return parse_meta_yaml_containerized(
            text,
            for_pinning=for_pinning,
            platform=platform,
            arch=arch,
            cbc_path=cbc_path,
            orig_cbc_path=orig_cbc_path,
            log_debug=log_debug,
        )
    else:
        return parse_meta_yaml_local(
            text,
            for_pinning=for_pinning,
            platform=platform,
            arch=arch,
            cbc_path=cbc_path,
            orig_cbc_path=orig_cbc_path,
            log_debug=log_debug,
        )


def parse_meta_yaml_containerized(
    text: str,
    for_pinning=False,
    platform=None,
    arch=None,
    cbc_path=None,
    orig_cbc_path=None,
    log_debug=False,
) -> "RecipeTypedDict":
    """Parse the meta.yaml.

    **This function runs the parsing in a container.**

    Parameters
    ----------
    text : str
        The raw text in conda-forge feedstock meta.yaml file
    for_pinning : bool, optional
        If True, render the meta.yaml for pinning migrators, by default False.
    platform : str, optional
        The platform (e.g., 'linux', 'osx', 'win').
    arch : str, optional
        The CPU architecture (e.g., '64', 'aarch64').
    cbc_path : str, optional
        The path to global pinning file.
    orig_cbc_path : str, optional
        If not None, the original conda build config file to put next to
        the recipe while parsing.
    log_debug : bool, optional
        If True, print extra debugging info. Default is False.

    Returns
    -------
    dict :
        The parsed YAML dict. If parsing fails, returns an empty dict. May raise
        for some errors. Have fun.
    """
    args = [
        "conda-forge-tick-container",
        "parse-meta-yaml",
    ]

    args += get_default_log_level_args(logger)

    if platform is not None:
        args += ["--platform", platform]

    if arch is not None:
        args += ["--arch", arch]

    if log_debug:
        args += ["--log-debug"]

    if for_pinning:
        args += ["--for-pinning"]

    def _run(_args, _mount_dir):
        return run_container_operation(
            _args,
            input=text,
            mount_readonly=True,
            mount_dir=_mount_dir,
            extra_container_args=[
                "-e",
                f"{ENV_CONDA_FORGE_ORG}={settings().conda_forge_org}",
                "-e",
                f"{ENV_GRAPH_GITHUB_BACKEND_REPO}={settings().graph_github_backend_repo}",
            ],
        )

    if (cbc_path is not None and os.path.exists(cbc_path)) or (
        orig_cbc_path is not None and os.path.exists(orig_cbc_path)
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chmod(tmpdir, 0o755)

            if cbc_path is not None and os.path.exists(cbc_path):
                with open(os.path.join(tmpdir, "cbc_path.yaml"), "w") as fp:
                    with open(cbc_path) as fp_r:
                        fp.write(fp_r.read())
                args += ["--cbc-path", "/cf_feedstock_ops_dir/cbc_path.yaml"]

            if orig_cbc_path is not None and os.path.exists(orig_cbc_path):
                with open(os.path.join(tmpdir, "orig_cbc_path.yaml"), "w") as fp:
                    with open(orig_cbc_path) as fp_r:
                        fp.write(fp_r.read())
                args += ["--orig-cbc-path", "/cf_feedstock_ops_dir/orig_cbc_path.yaml"]

            data = _run(args, tmpdir)
    else:
        data = _run(args, None)

    return data


def parse_meta_yaml_local(
    text: str,
    for_pinning=False,
    platform=None,
    arch=None,
    cbc_path=None,
    orig_cbc_path=None,
    log_debug=False,
) -> "RecipeTypedDict":
    """Parse the meta.yaml.

    Parameters
    ----------
    text : str
        The raw text in conda-forge feedstock meta.yaml file
    for_pinning : bool, optional
        If True, render the meta.yaml for pinning migrators, by default False.
    platform : str, optional
        The platform (e.g., 'linux', 'osx', 'win').
    arch : str, optional
        The CPU architecture (e.g., '64', 'aarch64').
    cbc_path : str, optional
        The path to global pinning file.
    orig_cbc_path : str, optional
        If not None, the original conda build config file to put next to
        the recipe while parsing.
    log_debug : bool, optional
        If True, print extra debugging info. Default is False.

    Returns
    -------
    dict :
        The parsed YAML dict. If parsing fails, returns an empty dict. May raise
        for some errors. Have fun.

    Raises
    ------
    RuntimeError
        If parsing fails.
    """

    def _run(*, use_orig_cbc_path):
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="The environment variable",
                category=UserWarning,
                module=r"conda_build\.environ",
            )

            class RenderingFilter(logging.Filter):
                def filter(self, record):
                    if (
                        record.msg.startswith("No numpy version specified")
                        or record.msg.startswith("Setting build platform")
                        or record.msg.startswith("Setting build arch")
                    ):
                        return False
                    return True

            rendering_filter = RenderingFilter()
            try:
                logging.getLogger("conda_build.metadata").addFilter(rendering_filter)

                return _parse_meta_yaml_impl(
                    text,
                    for_pinning=for_pinning,
                    platform=platform,
                    arch=arch,
                    cbc_path=cbc_path,
                    log_debug=log_debug,
                    orig_cbc_path=(orig_cbc_path if use_orig_cbc_path else None),
                )
            finally:
                logging.getLogger("conda_build.metadata").removeFilter(rendering_filter)

    try:
        return _run(use_orig_cbc_path=True)
    except (SystemExit, Exception):
        logger.debug("parsing w/ conda_build_config.yaml failed! trying without...")
        try:
            return _run(use_orig_cbc_path=False)
        except (SystemExit, Exception) as e:
            raise RuntimeError(
                "conda build error: %s\n%s"
                % (
                    repr(e),
                    traceback.format_exc(),
                ),
            )


def _parse_meta_yaml_impl(
    text: str,
    for_pinning=False,
    platform=None,
    arch=None,
    cbc_path=None,
    log_debug=False,
    orig_cbc_path=None,
) -> "RecipeTypedDict":
    import conda_build.api
    import conda_build.environ
    from conda_build.config import Config
    from conda_build.metadata import MetaData, parse
    from conda_build.variants import explode_variants

    if logger.getEffectiveLevel() <= logging.DEBUG:
        log_debug = True

    if cbc_path is not None and arch is not None and platform is not None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "meta.yaml"), "w") as fp:
                fp.write(text)
            if orig_cbc_path is not None and os.path.exists(orig_cbc_path):
                with open(orig_cbc_path) as fp_r:
                    with open(
                        os.path.join(tmpdir, "conda_build_config.yaml"),
                        "w",
                    ) as fp_w:
                        fp_w.write(fp_r.read())

            def _run_parsing():
                logger.debug(
                    "parsing for platform %s with cbc %s and arch %s",
                    platform,
                    cbc_path,
                    arch,
                )
                config = conda_build.config.get_or_merge_config(
                    None,
                    platform=platform,
                    arch=arch,
                    variant_config_files=[
                        cbc_path,
                    ],
                )
                _cbc, _ = conda_build.variants.get_package_combined_spec(
                    tmpdir,
                    config=config,
                )
                return config, _cbc

            if not log_debug:
                fout = io.StringIO()
                ferr = io.StringIO()
                # this code did use wulritzer.sys_pipes but that seemed
                # to cause conda-build to hang
                # versions:
                #   wurlitzer 3.0.2 py38h50d1736_1    conda-forge
                #   conda     4.11.0           py38h50d1736_0    conda-forge
                #   conda-build   3.21.7           py38h50d1736_0    conda-forge
                with (
                    contextlib.redirect_stdout(
                        fout,
                    ),
                    contextlib.redirect_stderr(ferr),
                ):
                    config, _cbc = _run_parsing()
            else:
                config, _cbc = _run_parsing()

            cfg_as_dict = {}
            for var in explode_variants(_cbc):
                try:
                    m = MetaData(tmpdir, config=config, variant=var)
                except SystemExit as e:
                    raise RuntimeError(repr(e))
                cfg_as_dict.update(conda_build.environ.get_dict(m=m))

            for key in cfg_as_dict:
                try:
                    if cfg_as_dict[key].startswith("/"):
                        cfg_as_dict[key] = key
                except Exception as e:
                    logger.debug(
                        "key-val not string: %s: %s", key, cfg_as_dict[key], exc_info=e
                    )
                    pass

        cbc = Config(
            platform=platform,
            arch=arch,
            variant=cfg_as_dict,
        )
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "meta.yaml"), "w") as fp:
                fp.write(text)

            _cfg = {}
            if platform is not None:
                _cfg["platform"] = platform
            if arch is not None:
                _cfg["arch"] = arch
            cbc = Config(**_cfg)

            try:
                m = MetaData(tmpdir)
                cfg_as_dict = conda_build.environ.get_dict(m=m)
            except SystemExit as e:
                raise RuntimeError(repr(e))

    logger.debug("jinja2 environmment:\n%s", pprint.pformat(cfg_as_dict))

    if for_pinning:
        content = _render_meta_yaml(text, for_pinning=for_pinning, **cfg_as_dict)
    else:
        content = _render_meta_yaml(text, **cfg_as_dict)

    try:
        return parse(content, cbc)
    except Exception:
        import traceback

        logger.debug("parse failure:\n%s", traceback.format_exc())
        logger.debug("parse template: %s", text)
        logger.debug("parse context:\n%s", pprint.pformat(cfg_as_dict))
        raise


class UniversalSet(Set):
    """The universal set, or identity of the set intersection operation."""

    def __and__(self, other: Set) -> Set:
        return other

    def __rand__(self, other: Set) -> Set:
        return other

    def __contains__(self, item: Any) -> bool:
        return True

    def __iter__(self) -> typing.Iterator[Any]:
        return self

    def __next__(self) -> typing.NoReturn:
        raise StopIteration

    def __len__(self) -> int:
        return float("inf")


class NullUndefined(jinja2.Undefined):
    def __unicode__(self) -> str:
        return self._undefined_name

    def __getattr__(self, name: Any) -> str:
        return f"{self}.{name}"

    def __getitem__(self, name: Any) -> str:
        return f'{self}["{name}"]'


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(asctime)-15s %(levelname)-8s %(name)s || %(message)s",
        level=level.upper(),
    )
    logging.getLogger("urllib3").setLevel(logging.INFO)
    logging.getLogger("github3").setLevel(logging.WARNING)


# TODO: upstream this into networkx?
def pluck(G: nx.DiGraph, node_id: Any) -> None:
    """Remove a node from a graph preserving structure.

    This will fuse edges together so that connectivity of the graph is not affected by
    removal of a node.  This function operates in-place.

    Parameters
    ----------
    G : networkx.Graph
    node_id : hashable

    """
    if node_id in G.nodes:
        new_edges = list(
            itertools.product(
                {_in for (_in, _) in G.in_edges(node_id)} - {node_id},
                {_out for (_, _out) in G.out_edges(node_id)} - {node_id},
            ),
        )
        G.remove_node(node_id)
        G.add_edges_from(new_edges)


def dump_graph_json(gx: nx.DiGraph, filename: str = "graph.json") -> None:
    nld = nx.node_link_data(gx, edges="links")
    links = nld["links"]
    links2 = sorted(links, key=lambda x: f"{x['source']}{x['target']}")
    nld["links"] = links2

    lzj = LazyJson(filename)
    with lzj as attrs:
        attrs.update(nld)


def dump_graph(
    gx: nx.DiGraph,
    filename: str = "graph.json",
    tablename: str = "graph",
    region: str = "us-east-2",
) -> None:
    dump_graph_json(gx, filename)


def load_existing_graph(filename: str = DEFAULT_GRAPH_FILENAME) -> nx.DiGraph:
    """
    Load the graph from a file using the lazy json backend.
    If the file does not exist, it is initialized with empty JSON before performing any reads.
    If empty JSON is encountered, a ValueError is raised.
    If you expect the graph to be possibly empty JSON (i.e. not initialized), use load_graph.

    Returns
    -------
    nx.DiGraph
        The graph loaded from the file.

    Raises
    ------
    ValueError
        If the file contains empty JSON.
    """
    gx = load_graph(filename)
    if gx is None:
        raise ValueError(f"Graph file {filename} contains empty JSON")
    return gx


def load_graph(filename: str = DEFAULT_GRAPH_FILENAME) -> Optional[nx.DiGraph]:
    """Load the graph from a file using the lazy json backend.
    If the file does not exist, it is initialized with empty JSON.
    If you expect the graph to be non-empty JSON, use load_existing_graph.

    Returns
    -------
    nx.DiGraph or None
        The graph, or None if the file is empty JSON
    """
    dta = copy.deepcopy(LazyJson(filename).data)
    if dta:
        return nx.node_link_graph(dta, edges="links")
    else:
        return None


# TODO: This type does not support generics yet sadly
# cc https://github.com/python/mypy/issues/3863
if typing.TYPE_CHECKING:

    class JsonFriendly(TypedDict, total=False):
        keys: typing.List[str]
        data: dict
        PR: dict


@typing.overload
def frozen_to_json_friendly(fz: None, pr: Optional[LazyJson] = None) -> None:
    pass


@typing.overload
def frozen_to_json_friendly(fz: Any, pr: Optional[LazyJson] = None) -> "JsonFriendly":
    pass


@typing.no_type_check
def frozen_to_json_friendly(fz, pr: Optional[LazyJson] = None):
    if fz is None:
        return None
    d = {"data": dict(fz)}
    if pr:
        d["PR"] = pr
    return d


@typing.overload
def as_iterable(x: dict) -> Tuple[dict]: ...


@typing.overload
def as_iterable(x: str) -> Tuple[str]: ...


@typing.overload
def as_iterable(x: Iterable[T]) -> Iterable[T]: ...


@typing.overload
def as_iterable(x: T) -> Tuple[T]: ...


@typing.no_type_check
def as_iterable(iterable_or_scalar):
    """Convert an object into an iterable.

    Parameters
    ----------
    iterable_or_scalar : anything

    Returns
    -------
    l : iterable
        If `obj` was None, return the empty tuple.
        If `obj` was not iterable returns a 1-tuple containing `obj`.
        Otherwise return `obj`

    Notes
    -----
    Although both string types and dictionaries are iterable in Python, we are
    treating them as not iterable in this method.  Thus, as_iterable(dict())
    returns (dict, ) and as_iterable(string) returns (string, )

    Examples
    --------
    >>> as_iterable(1)
    (1,)
    >>> as_iterable([1, 2, 3])
    [1, 2, 3]
    >>> as_iterable("my string")
    ("my string", )
    >>> as_iterable({'a': 1})
    ({'a': 1}, )
    """
    if iterable_or_scalar is None:
        return ()
    elif isinstance(iterable_or_scalar, (str, bytes)):
        return (iterable_or_scalar,)
    elif hasattr(iterable_or_scalar, "__iter__"):
        return iterable_or_scalar
    else:
        return (iterable_or_scalar,)


def sanitize_string(instr: str) -> str:
    from conda_forge_tick.env_management import SensitiveEnv

    with sensitive_env() as env:
        tokens = [env.get(token, None) for token in SensitiveEnv.SENSITIVE_KEYS]

    for token in tokens:
        if token is not None:
            instr = instr.replace(token, "~" * len(token))

    return instr


def get_keys_default(dlike, keys, default, final_default):
    defaults = [default] * (len(keys) - 1) + [final_default]
    val = dlike
    for k, _d in zip(keys, defaults):
        val = val.get(k, _d) or _d
    return val


def get_bot_run_url():
    return os.environ.get("RUN_URL", "")


def get_migrator_report_name_from_pr_data(migration):
    """Get the canonical name of a migration from the PR data."""
    if "version" in migration["data"]:
        return migration["data"]["version"]
    elif "name" in migration["data"]:
        return migration["data"]["name"].lower().replace(" ", "")
    elif "migrator_name" in migration["data"]:
        return migration["data"]["migrator_name"].lower()
    else:
        logger.warning(
            "Could not extract migrator report name for migration: %s",
            migration["data"],
        )
        return None


@contextlib.contextmanager
def change_log_level(logger, new_level):
    """Context manager to temporarily change the logging level of a logger."""
    if isinstance(logger, str):
        logger = logging.getLogger(logger)

    if isinstance(new_level, str):
        new_level = getattr(logging, new_level.upper())

    saved_logger_level = logger.level
    try:
        logger.setLevel(new_level)
        yield
    finally:
        logger.setLevel(saved_logger_level)


def run_command_hiding_token(args: list[str], token: str, **kwargs) -> int:
    """Run a command and hide the token in the output.

    Prints the outputs (stdout and stderr) of the subprocess.CompletedProcess object.
    The token or tokens will be replaced with a string of asterisks of the same length.

    If stdout or stderr is None, it will not be printed.

    Parameters
    ----------
    args
        The command to run.
    token
        The token to hide in the output.
    kwargs
        additional arguments for subprocess.run

    Returns
    -------
    int
        The return code of the command.

    Raises
    ------
    ValueError
        If the kwargs contain 'text', 'stdout', or 'stderr'.
    """
    if kwargs.keys() & {"text", "stdout", "stderr"}:
        raise ValueError("text, stdout, and stderr are not allowed in kwargs")

    p = subprocess.run(
        args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
    )

    out, err = p.stdout, p.stderr

    for captured, out_dev in [(out, sys.stdout), (err, sys.stderr)]:
        if captured is None:
            continue

        captured = captured.replace(token, "*" * len(token))
        print(captured, file=out_dev, end="")
        out_dev.flush()

    return p.returncode


def _is_comment_or_empty(line):
    return line.strip() == "" or line.strip().startswith("#")


def extract_section_from_yaml_text(
    yaml_text: str,
    section_name: str,
    exclude_requirements: bool = False,
) -> list[str]:
    """Extract a section from YAML as text.

    Parameters
    ----------
    yaml_text : str
        The raw YAML text.
    section_name : str
        The section name to extract.
    exclude_requirements : bool, optional
        If True, exclude any sections in a `requirements` block. Set to
        True if you want to extract the `build` section but not the `requirements.build`
        section. Default is False.

    Returns
    -------
    list[str]
        A list of strings for the extracted sections.
    """
    # normalize the indents etc.
    try:
        yaml_text = CondaMetaYAML(yaml_text).dumps()
    except Exception as e:
        logger.debug(
            "Failed to normalize the YAML text due to error %s. We will try to parse anyways!",
            repr(e),
        )
        pass

    lines = yaml_text.splitlines()

    in_requirements = False
    requirements_indent = None
    section_indent = None
    section_start = None
    found_sections = []

    for loc, line in enumerate(lines):
        if (
            section_indent is not None
            and not _is_comment_or_empty(line)
            and len(line) - len(line.lstrip()) <= section_indent
        ):
            if (not exclude_requirements) or (
                exclude_requirements and not in_requirements
            ):
                found_sections.append("\n".join(lines[section_start:loc]))
            section_indent = None
            section_start = None

        if line.lstrip().startswith(f"{section_name}:"):
            section_indent = len(line) - len(line.lstrip())
            section_start = loc

        # blocks for detecting if we are in requirements
        # these blocks have to come after the blocks above since a section can end
        # with the 'requirements:' line and that is OK.
        if (
            requirements_indent is not None
            and not _is_comment_or_empty(line)
            and len(line) - len(line.lstrip()) <= requirements_indent
        ):
            in_requirements = False
            requirements_indent = None

        if line.lstrip().startswith("requirements:"):
            requirements_indent = len(line) - len(line.lstrip())
            in_requirements = True

    if section_start is not None:
        if (not exclude_requirements) or (exclude_requirements and not in_requirements):
            found_sections.append("\n".join(lines[section_start:]))

    return found_sections


def version_follows_conda_spec(version: str | bool) -> bool:
    if isinstance(version, str):
        try:
            VersionOrder(version.replace("-", "."))
        except Exception:
            return False
        else:
            return True
    else:
        return False


def pr_can_be_archived(
    pr: dict | LazyJson, now: int | float | None = None, archive_empty_prs: bool = False
) -> bool:
    """
    Return true if a PR can be archived.

    A PR can be archived if it has been closed for at least the amount of time
    in settings().pull_request_reopen_window.

    Parameters
    ----------
    pr : dict | LazyJson
        The PR json.
    now : int | float | None
        The current unix timestamp. If None, a call to time.time is made.
    archive_empty_prs : bool
        If True, PRs that have no data in the json blob are considered eligible to
        be archived.

    Returns
    -------
    bool
    """
    if now is None:
        now = time.time()

    if not isinstance(pr, LazyJson):
        pr = contextlib.nullcontext(pr)

    with pr as pr:
        pr_lm = pr.get("Last-Modified", None)
        if pr_lm is not None:
            pr_lm = dateparser.parse(pr_lm)

        if (
            pr_lm is None
            or now - pr_lm.timestamp() > settings().pull_request_reopen_window
        ) and (
            pr.get("state", None) == "closed" or (archive_empty_prs and pr.data == {})
        ):
            return True
        else:
            return False


def get_platform_arch_from_ci_support_filename(ci_support_filename):
    """Extract the platform and architecture as `(plat, arch)` from the ".ci_support" filename."""
    cbc_name_parts = ci_support_filename.replace(".yaml", "").split("_")
    plat = cbc_name_parts[0]
    if len(cbc_name_parts) == 1:
        arch = "64"
    else:
        if cbc_name_parts[1] in ["64", "aarch64", "ppc64le", "arm64"]:
            arch = cbc_name_parts[1]
        else:
            arch = "64"
    # some older cbc yaml files have things like "linux64"
    for _tt in ["64", "aarch64", "ppc64le", "arm64", "32"]:
        if plat.endswith(_tt):
            plat = plat[: -len(_tt)]
            break
    return (plat, arch)
