import collections.abc
import hashlib
import logging
import os
import re
import tempfile
import typing
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Optional, Set, Union

import requests
import yaml
from conda_forge_feedstock_ops.container_utils import (
    get_default_log_level_args,
    run_container_operation,
    should_use_container,
)
from requests.models import Response

from conda_forge_tick.settings import (
    ENV_CONDA_FORGE_ORG,
    ENV_GRAPH_GITHUB_BACKEND_REPO,
    settings,
)

if typing.TYPE_CHECKING:
    from mypy_extensions import TestTypedDict

    from conda_forge_tick.migrators_types import RecipeTypedDict

from conda_forge_tick.lazy_json_backends import LazyJson, dumps, loads
from conda_forge_tick.utils import (
    as_iterable,
    parse_meta_yaml,
    parse_recipe_yaml,
    sanitize_string,
)

from .migrators_types import PackageName, RequirementsTypedDict

logger = logging.getLogger(__name__)

PIN_SEP_PAT = re.compile(r" |>|<|=|\[")

# this dictionary maps feedstocks to their output
# that would be available in a bootstrapping scenario
# for these nodes, we only use the bootstrap requirements
# to build graph edges
BOOTSTRAP_MAPPINGS = {}


def _dedupe_list_ordered(list_with_dupes):
    if not isinstance(list_with_dupes, list):
        return list_with_dupes

    if not all(isinstance(x, str) for x in list_with_dupes):
        return list_with_dupes

    seen = set()
    list_without_dupes = []
    for item in list_with_dupes:
        if item not in seen:
            seen.add(item)
            list_without_dupes.append(item)
    return list_without_dupes


def _dedupe_meta_yaml(meta_yaml):
    """Deduplicate a meta.yaml dict recursively."""
    if isinstance(meta_yaml, dict):
        for key, value in meta_yaml.items():
            meta_yaml[key] = _dedupe_meta_yaml(value)
    elif isinstance(meta_yaml, list):
        for i, item in enumerate(meta_yaml):
            meta_yaml[i] = _dedupe_meta_yaml(item)
        meta_yaml = _dedupe_list_ordered(meta_yaml)

    return meta_yaml


def _get_requirements(
    meta_yaml: "RecipeTypedDict",
    outputs: bool = True,
    build: bool = True,
    host: bool = True,
    run: bool = True,
    outputs_to_keep: Optional[Set["PackageName"]] = None,
) -> "Set[PackageName]":
    """Get the list of recipe requirements from a meta.yaml dict.

    Parameters
    ----------
    meta_yaml: `dict`
        a parsed meta YAML dict
    outputs : `bool`
        if `True` (default) return top-level requirements _and_ all
        requirements in `outputs`, otherwise just return top-level
        requirements.
    build, host, run : `bool`
        include (`True`) or not (`False`) requirements from these sections

    Returns
    -------
    reqs : `set`
        the set of recipe requirements
    """
    kw = dict(build=build, host=host, run=run)
    if outputs_to_keep:
        reqs = set()
        outputs_ = meta_yaml.get("outputs", []) or [] if outputs else []
        for output in outputs_:
            if output.get("name") in outputs_to_keep:
                reqs |= _parse_requirements(output.get("requirements", {}) or {}, **kw)
    else:
        reqs = _parse_requirements(meta_yaml.get("requirements", {}), **kw)
        outputs_ = meta_yaml.get("outputs", []) or [] if outputs else []
        for output in outputs_:
            for req in _parse_requirements(output.get("requirements", {}) or {}, **kw):
                reqs.add(req)
    return reqs


def _parse_requirements(
    req: Union[None, typing.List[str], "RequirementsTypedDict"],
    build: bool = True,
    host: bool = True,
    run: bool = True,
) -> typing.MutableSet["PackageName"]:
    """Flatten a YAML requirements section into a list of names."""
    if not req:  # handle None as empty
        return set()
    if isinstance(req, list):  # simple list goes to both host and run
        reqlist = req if (host or run) else []
    else:
        _build = list(as_iterable(req.get("build", []) or [] if build else []))
        _host = list(as_iterable(req.get("host", []) or [] if host else []))
        _run = list(as_iterable(req.get("run", []) or [] if run else []))
        reqlist = _build + _host + _run

    packages = (PIN_SEP_PAT.split(x)[0].lower() for x in reqlist if x is not None)
    return {typing.cast("PackageName", pkg) for pkg in packages}


def _extract_requirements(meta_yaml, outputs_to_keep=None):
    strong_exports = False
    requirements_dict = defaultdict(set)

    if outputs_to_keep:
        metas = []
        for output in meta_yaml.get("outputs", []) or []:
            if output.get("name") in outputs_to_keep:
                metas.append(output)
    else:
        metas = [meta_yaml] + meta_yaml.get("outputs", []) or []

    for block in metas:
        req: "RequirementsTypedDict" = block.get("requirements", {}) or {}
        if isinstance(req, list):
            requirements_dict["run"].update(set(req))
            continue
        for section in ["build", "host", "run"]:
            requirements_dict[section].update(
                list(as_iterable(req.get(section, []) or [])),
            )

        test: "TestTypedDict" = block.get("test", {}) or {}
        requirements_dict["test"].update(test.get("requirements", []) or [])
        requirements_dict["test"].update(test.get("requires", []) or [])

        if "tests" in block:
            for test in block.get("tests", []):
                # only script tests have requirements
                if "requirements" in test:
                    run_reqs = test["requirements"].get("run", [])
                    build_reqs = test["requirements"].get("build", [])
                    requirements_dict["test"].update(run_reqs + build_reqs)
                if "python" in test:
                    # if pip_check is unset or True, we need pip
                    if test.get("pip_check", True):
                        requirements_dict["test"].add("pip")

        run_exports = (block.get("build", {}) or {}).get("run_exports", {})
        if isinstance(run_exports, dict) and run_exports.get("strong"):
            strong_exports = True
    for k in list(requirements_dict.keys()):
        requirements_dict[k] = {v for v in requirements_dict[k] if v}
    req_no_pins = {
        k: {PIN_SEP_PAT.split(x)[0].lower() for x in v}
        for k, v in dict(requirements_dict).items()
    }
    return dict(requirements_dict), req_no_pins, strong_exports


def _fetch_static_repo(name, dest):
    found_branch = None
    for branch in ["main", "master"]:
        try:
            r = requests.get(
                f"https://github.com/{settings().conda_forge_org}/{name}-feedstock/archive/{branch}.zip",
            )
            r.raise_for_status()
            found_branch = branch
            break
        except Exception:
            pass

    if r.status_code != 200:
        logger.error(
            "Something odd happened when fetching feedstock %s: %d", name, r.status_code
        )
        return r

    zname = os.path.join(dest, f"{name}-feedstock-{found_branch}.zip")

    with open(zname, "wb") as fp:
        fp.write(r.content)

    z = zipfile.ZipFile(zname)
    z.extractall(path=dest)
    dest_dir = os.path.join(dest, os.path.split(z.namelist()[0])[0])
    return dest_dir


def _clean_req_nones(reqs):
    for section in ["build", "host", "run"]:
        # We make sure to set a section only if it is actually in
        # the recipe. Adding a section when it is not there might
        # confuse migrators trying to move CB2 recipes to CB3.
        if section in reqs:
            val = reqs.get(section, [])
            if val is None:
                val = []
            if isinstance(val, str):
                val = [val]
            reqs[section] = [v for v in val if v is not None]
    return reqs


def populate_feedstock_attributes(
    name: str,
    existing_node_attrs: typing.MutableMapping[str, typing.Any],
    meta_yaml: str | None = None,
    recipe_yaml: str | None = None,
    conda_forge_yaml: str | None = None,
    mark_not_archived: bool = False,
    feedstock_dir: str | Path | None = None,
) -> dict[str, typing.Any]:
    """
    Parse the various configuration information into the node_attrs of a feedstock.

    Parameters
    ----------
    name
        The name of the feedstock.
    existing_node_attrs
        The existing node_attrs of the feedstock. Pass an empty dict if none.
    meta_yaml
        The meta.yaml file as a string.
    recipe_yaml
        The recipe.yaml file as a string.
    conda_forge_yaml
        The conda-forge.yaml file as a string.
    mark_not_archived
        If True, forcibly mark the feedstock as not archived in the node attrs,
        even if it is archived.
    feedstock_dir
        The directory where the feedstock is located. If None, some information
        will not be available.

    Returns
    -------
    dict[str, Any]
        A dictionary with the new node_attrs of the feedstock, with only some
        fields populated.

    Raises
    ------
    ValueError
        If both `meta_yaml` and `recipe_yaml` are provided.
        If neither `meta_yaml` nor `recipe_yaml` are provided.
    """
    from conda_forge_tick.chaindb import ChainDB, _convert_to_dict

    node_attrs = {key: value for key, value in existing_node_attrs.items()}

    if isinstance(feedstock_dir, str):
        feedstock_dir = Path(feedstock_dir)

    if (meta_yaml is None and recipe_yaml is None) or (
        meta_yaml is not None and recipe_yaml is not None
    ):
        raise ValueError("Either `meta_yaml` or `recipe_yaml` needs to be given.")

    node_attrs.update(
        {"feedstock_name": name, "parsing_error": False, "branch": "main"}
    )

    if mark_not_archived:
        node_attrs.update({"archived": False})

    # strip out old keys - this removes old platforms when one gets disabled
    for key in list(node_attrs.keys()):
        if key.endswith("meta_yaml") or key.endswith("requirements") or key == "req":
            del node_attrs[key]

    if isinstance(meta_yaml, str):
        node_attrs["raw_meta_yaml"] = meta_yaml
    elif isinstance(recipe_yaml, str):
        node_attrs["raw_meta_yaml"] = recipe_yaml

    # Get the conda-forge.yml
    if isinstance(conda_forge_yaml, str):
        try:
            node_attrs["conda-forge.yml"] = {
                k: v for k, v in yaml.safe_load(conda_forge_yaml).items()
            }
        except Exception as e:
            import traceback

            trb = traceback.format_exc()
            node_attrs["parsing_error"] = sanitize_string(
                f"feedstock parsing error: cannot load conda-forge.yml: {e}\n{trb}"
            )
            return node_attrs

    if feedstock_dir is not None:
        logger.debug(
            "# of ci support files: %s",
            len(list(feedstock_dir.joinpath(".ci_support").glob("*.yaml"))),
        )

    try:
        if (
            feedstock_dir is not None
            and len(list(feedstock_dir.joinpath(".ci_support").glob("*.yaml"))) > 0
        ):
            recipe_dir = feedstock_dir / "recipe"
            ci_support_files = sorted(
                feedstock_dir.joinpath(".ci_support").glob("*.yaml")
            )
            variant_yamls = []
            plat_archs = []
            for cbc_path in ci_support_files:
                logger.debug("parsing conda-build config: %s", cbc_path)
                cbc_name = cbc_path.name
                cbc_name_parts = cbc_name.replace(".yaml", "").split("_")
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
                plat_archs.append((plat, arch))

                if isinstance(meta_yaml, str):
                    variant_yamls.append(
                        parse_meta_yaml(
                            meta_yaml,
                            platform=plat,
                            arch=arch,
                            cbc_path=cbc_path,
                            orig_cbc_path=os.path.join(
                                recipe_dir,
                                "conda_build_config.yaml",
                            ),
                        ),
                    )
                    variant_yamls[-1]["schema_version"] = 0
                elif isinstance(recipe_yaml, str):
                    platform_arch = (
                        f"{plat}-{arch}"
                        if isinstance(plat, str) and isinstance(arch, str)
                        else None
                    )
                    variant_yamls.append(
                        parse_recipe_yaml(
                            recipe_yaml,
                            platform_arch=platform_arch,
                            cbc_path=cbc_path,
                        ),
                    )
                    variant_yamls[-1]["schema_version"] = variant_yamls[-1].get(
                        "schema_version", 1
                    )

                # sometimes the requirements come out to None or [None]
                # and this ruins the aggregated meta_yaml / breaks stuff
                logger.debug("getting reqs for config: %s", cbc_path)
                if "requirements" in variant_yamls[-1]:
                    variant_yamls[-1]["requirements"] = _clean_req_nones(
                        variant_yamls[-1]["requirements"],
                    )
                if "outputs" in variant_yamls[-1]:
                    for iout in range(len(variant_yamls[-1]["outputs"])):
                        if "requirements" in variant_yamls[-1]["outputs"][iout]:
                            variant_yamls[-1]["outputs"][iout]["requirements"] = (
                                _clean_req_nones(
                                    variant_yamls[-1]["outputs"][iout]["requirements"],
                                )
                            )

                # collapse them down
                logger.debug("collapsing reqs for %s", name)
                final_cfgs = {}
                for plat_arch, varyml in zip(plat_archs, variant_yamls):
                    if plat_arch not in final_cfgs:
                        final_cfgs[plat_arch] = []
                    final_cfgs[plat_arch].append(varyml)
                for k in final_cfgs:
                    ymls = final_cfgs[k]
                    final_cfgs[k] = _dedupe_meta_yaml(_convert_to_dict(ChainDB(*ymls)))

                plat_archs.clear()
                variant_yamls.clear()
                for k, v in final_cfgs.items():
                    plat_archs.append(k)
                    variant_yamls.append(v)
        else:
            logger.debug("doing generic parsing")
            plat_archs = [("win", "64"), ("osx", "64"), ("linux", "64")]
            for k in set(node_attrs["conda-forge.yml"].get("provider", {})):
                if "_" in k:
                    plat_archs.append(tuple(k.split("_")))
            if isinstance(meta_yaml, str):
                variant_yamls = [
                    parse_meta_yaml(meta_yaml, platform=plat, arch=arch)
                    for plat, arch in plat_archs
                ]
            elif isinstance(recipe_yaml, str):
                raise NotImplementedError(
                    "recipe_yaml generic parsing not implemented yet! Ensure the feedstock has .ci_support files."
                )
    except Exception as e:
        import traceback

        trb = traceback.format_exc()
        node_attrs["parsing_error"] = sanitize_string(
            f"feedstock parsing error: cannot rendering recipe: {e}\n{trb}"
        )
        raise

    logger.debug("platforms: %s", plat_archs)
    node_attrs["platforms"] = ["_".join(k) for k in plat_archs]

    # this makes certain that we have consistent ordering
    sorted_variant_yamls = [x for _, x in sorted(zip(plat_archs, variant_yamls))]
    yaml_dict = ChainDB(*sorted_variant_yamls)
    if not yaml_dict:
        logger.error("Something odd happened when parsing recipe %s", name)
        node_attrs["parsing_error"] = (
            "feedstock parsing error: could not combine metadata dicts across platforms"
        )
        return node_attrs

    node_attrs["meta_yaml"] = _dedupe_meta_yaml(_convert_to_dict(yaml_dict))
    meta_yaml = node_attrs["meta_yaml"]

    # remove all plat-arch specific keys to remove old ones if a combination is disabled
    for k in list(node_attrs.keys()):
        if k in ["raw_meta_yaml", "total_requirements"]:
            continue
        if k.endswith("_meta_yaml") or k.endswith("_requirements"):
            node_attrs.pop(k)

    for k, v in zip(plat_archs, variant_yamls):
        plat_arch_name = "_".join(k)
        node_attrs[f"{plat_arch_name}_meta_yaml"] = v
        _, node_attrs[f"{plat_arch_name}_requirements"], _ = _extract_requirements(
            v,
            outputs_to_keep=BOOTSTRAP_MAPPINGS.get(name, None),
        )

    (
        node_attrs["total_requirements"],
        node_attrs["requirements"],
        node_attrs["strong_exports"],
    ) = _extract_requirements(
        meta_yaml,
        outputs_to_keep=BOOTSTRAP_MAPPINGS.get(name, None),
    )

    # handle multi outputs
    outputs_names = set()
    if "outputs" in yaml_dict:
        outputs_names.update(
            set(
                list({d.get("name", "") for d in yaml_dict["outputs"]}),
            ),
        )
        # handle implicit meta packages
        if "run" in node_attrs.get("meta_yaml", {}).get("requirements", {}):
            outputs_names.add(meta_yaml["package"]["name"])
    # add in single package name
    else:
        outputs_names = {meta_yaml["package"]["name"]}
    node_attrs["outputs_names"] = outputs_names

    # TODO: Write schema for dict
    # TODO: remove this
    req = _get_requirements(
        yaml_dict,
        outputs_to_keep=BOOTSTRAP_MAPPINGS.get(name, []),
    )
    node_attrs["req"] = req

    # set name and version
    keys = [("package", "name"), ("package", "version")]
    missing_keys = [k[1] for k in keys if k[1] not in yaml_dict.get(k[0], {})]
    for k in keys:
        if k[1] not in missing_keys:
            node_attrs[k[1]] = yaml_dict[k[0]][k[1]]

    # sometimes a version is not given at the top level, so we check outputs
    # we do not know which version to take, but hopefully they are all the same
    if (
        "version" not in node_attrs
        and "outputs" in yaml_dict
        and len(yaml_dict["outputs"]) > 0
        and "version" in yaml_dict["outputs"][0]
    ):
        node_attrs["version"] = yaml_dict["outputs"][0]["version"]

    # set the url and hash
    node_attrs.pop("url", None)
    node_attrs.pop("hash_type", None)

    source = yaml_dict.get("source", [])
    if isinstance(source, collections.abc.Mapping):
        source = [source]
    source_keys: Set[str] = set()
    for s in source:
        if not node_attrs.get("url"):
            node_attrs["url"] = s.get("url")
        source_keys |= s.keys()

    kl = list(sorted(source_keys & hashlib.algorithms_available, reverse=True))
    if kl:
        node_attrs["hash_type"] = kl[0]

    return node_attrs


def load_feedstock_local(
    name: str,
    sub_graph: typing.MutableMapping,
    meta_yaml: str | None = None,
    recipe_yaml: str | None = None,
    conda_forge_yaml: str | None = None,
    mark_not_archived: bool = False,
) -> dict[str, typing.Any]:
    """Load a feedstock into subgraph based on its name. If meta_yaml and/or
    conda_forge_yaml are not provided, they will be fetched from the feedstock.

    Parameters
    ----------
    name : str
        Name of the feedstock
    sub_graph : MutableMapping
        The existing metadata if any
    meta_yaml : str | None
        The string meta.yaml, overrides the file in the feedstock if provided
    recipe_yaml: str | None
        The string recipe.yaml, overrides the file in the feedstock if provided
    conda_forge_yaml : Optional[str]
        The string conda-forge.yaml, overrides the file in the feedstock if provided
    mark_not_archived : bool
        If True, forcibly mark the feedstock as not archived in the node attrs.

    Returns
    -------
    sub_graph : MutableMapping
        The sub_graph, now updated with the feedstock metadata

    Raises
    ------
    ValueError
        If both `meta_yaml` and `recipe_yaml` are provided.
        If neither `meta_yaml` nor `recipe_yaml` are provided and no file is present in
        the feedstock.
    """
    new_sub_graph = {key: value for key, value in sub_graph.items()}

    if meta_yaml is not None and recipe_yaml is not None:
        raise ValueError("Only either `meta_yaml` or `recipe_yaml` can be overridden.")

    # pull down one copy of the repo
    with tempfile.TemporaryDirectory() as tmpdir:
        feedstock_dir = _fetch_static_repo(name, tmpdir)

        # If either `meta_yaml` or `recipe_yaml` is overridden, use that
        # otherwise use "meta.yaml" file if it exists
        # otherwise use "recipe.yaml" file if it exists
        # if nothing is overridden and no file is present, error out
        if meta_yaml is None and recipe_yaml is None:
            if isinstance(feedstock_dir, Response):
                new_sub_graph.update(
                    {"feedstock_name": name, "parsing_error": False, "branch": "main"}
                )

                if mark_not_archived:
                    new_sub_graph.update({"archived": False})

                new_sub_graph["parsing_error"] = sanitize_string(
                    f"make_graph: {feedstock_dir.status_code}"
                )
                return new_sub_graph

            meta_yaml_path = Path(feedstock_dir).joinpath("recipe", "meta.yaml")
            recipe_yaml_path = Path(feedstock_dir).joinpath("recipe", "recipe.yaml")
            if meta_yaml_path.exists():
                meta_yaml = meta_yaml_path.read_text()
            elif recipe_yaml_path.exists():
                recipe_yaml = recipe_yaml_path.read_text()
            else:
                raise ValueError(
                    "Either `meta.yaml` or `recipe.yaml` need to be present in the feedstock"
                )

        if conda_forge_yaml is None:
            conda_forge_yaml_path = Path(feedstock_dir).joinpath("conda-forge.yml")
            if conda_forge_yaml_path.exists():
                conda_forge_yaml = conda_forge_yaml_path.read_text()

        return populate_feedstock_attributes(
            name,
            new_sub_graph,
            meta_yaml=meta_yaml,
            recipe_yaml=recipe_yaml,
            conda_forge_yaml=conda_forge_yaml,
            mark_not_archived=mark_not_archived,
            feedstock_dir=feedstock_dir,
        )


def load_feedstock_containerized(
    name: str,
    sub_graph: typing.MutableMapping,
    meta_yaml: str | None = None,
    recipe_yaml: str | None = None,
    conda_forge_yaml: str | None = None,
    mark_not_archived: bool = False,
):
    """Load a feedstock into subgraph based on its name. If meta_yaml and/or
    conda_forge_yaml are not provided, they will be fetched from the feedstock.

    **This function runs the feedstock parsing in a container.**

    Parameters
    ----------
    name : str
        Name of the feedstock
    sub_graph : MutableMapping
        The existing metadata if any
    meta_yaml : str | None
        The string meta.yaml, overrides the file in the feedstock if provided
    recipe_yaml : str | None
        The string recipe.yaml, overrides the file in the feedstock if provided
    conda_forge_yaml : str | None
        The string conda-forge.yaml, overrides the file in the feedstock if provided
    mark_not_archived : bool
        If True, forcibly mark the feedstock as not archived in the node attrs.

    Returns
    -------
    sub_graph : MutableMapping
        The sub_graph, now updated with the feedstock metadata
    """
    if "feedstock_name" not in sub_graph:
        sub_graph["feedstock_name"] = name

    args = [
        "conda-forge-tick-container",
        "parse-feedstock",
        "--existing-feedstock-node-attrs",
        "-",
    ]

    args += get_default_log_level_args(logger)

    if meta_yaml is not None:
        args += ["--meta-yaml", meta_yaml]

    if recipe_yaml is not None:
        args += ["--recipe-yaml", recipe_yaml]

    if conda_forge_yaml is not None:
        args += ["--conda-forge-yaml", conda_forge_yaml]

    if mark_not_archived:
        args += ["--mark-not-archived"]

    json_blob = (
        dumps(sub_graph.data) if isinstance(sub_graph, LazyJson) else dumps(sub_graph)
    )

    data = run_container_operation(
        args,
        json_loads=loads,
        input=json_blob,
        extra_container_args=[
            "-e",
            f"{ENV_CONDA_FORGE_ORG}={settings().conda_forge_org}",
            "-e",
            f"{ENV_GRAPH_GITHUB_BACKEND_REPO}={settings().graph_github_backend_repo}",
        ],
    )

    return data


def load_feedstock(
    name: str,
    sub_graph: typing.MutableMapping,
    meta_yaml: str | None = None,
    recipe_yaml: str | None = None,
    conda_forge_yaml: str | None = None,
    mark_not_archived: bool = False,
    use_container: bool | None = None,
):
    """Load a feedstock into subgraph based on its name. If meta_yaml and/or
    conda_forge_yaml are not provided, they will be fetched from the feedstock.

    Parameters
    ----------
    name : str
        Name of the feedstock
    sub_graph : MutableMapping
        The existing metadata if any
    meta_yaml : str | None
        The string meta.yaml, overrides the file in the feedstock if provided
    recipe_yaml : str | None
        The string recipe.yaml, overrides the file in the feedstock if provided
    conda_forge_yaml : str | None
        The string conda-forge.yaml, overrides the file in the feedstock if provided
    mark_not_archived : bool
        If True, forcibly mark the feedstock as not archived in the node attrs.
    use_container : bool, optional
        Whether to use a container to run the version parsing.
        If None, the function will use a container if the environment
        variable `CF_FEEDSTOCK_OPS_IN_CONTAINER` is 'false'. This feature can be
        used to avoid container in container calls.

    Returns
    -------
    sub_graph : MutableMapping
        The sub_graph, now updated with the feedstock metadata
    """
    if should_use_container(use_container=use_container):
        return load_feedstock_containerized(
            name,
            sub_graph,
            meta_yaml=meta_yaml,
            recipe_yaml=recipe_yaml,
            conda_forge_yaml=conda_forge_yaml,
            mark_not_archived=mark_not_archived,
        )
    else:
        return load_feedstock_local(
            name,
            sub_graph,
            meta_yaml=meta_yaml,
            recipe_yaml=recipe_yaml,
            conda_forge_yaml=conda_forge_yaml,
            mark_not_archived=mark_not_archived,
        )
