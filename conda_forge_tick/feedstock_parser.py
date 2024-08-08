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
from requests.models import Response

if typing.TYPE_CHECKING:
    from mypy_extensions import TestTypedDict

    from conda_forge_tick.migrators_types import RecipeTypedDict

    from .migrators_types import PackageName, RequirementsTypedDict

from conda_forge_tick.lazy_json_backends import LazyJson, dumps, loads
from conda_forge_tick.utils import run_container_task

from .utils import as_iterable, parse_meta_yaml, parse_recipe_yaml

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
    """Get the list of recipe requirements from a meta.yaml dict

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
    """Flatten a YAML requirements section into a list of names"""
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
        test: "TestTypedDict" = block.get("test", {})
        requirements_dict["test"].update(test.get("requirements", []) or [])
        requirements_dict["test"].update(test.get("requires", []) or [])
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
                f"https://github.com/conda-forge/{name}-feedstock/archive/{branch}.zip",
            )
            r.raise_for_status()
            found_branch = branch
            break
        except Exception:
            pass

    if r.status_code != 200:
        logger.error(
            f"Something odd happened when fetching feedstock {name}: {r.status_code}",
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
    sub_graph: typing.MutableMapping,
    meta_yaml: str | None = None,
    recipe_yaml: str | None = None,
    conda_forge_yaml: str | None = None,
    mark_not_archived: bool = False,
    feedstock_dir: str | Path | None = None,
) -> typing.MutableMapping:
    """Parse the various configuration information into something usable"""

    from conda_forge_tick.chaindb import ChainDB, _convert_to_dict

    if isinstance(feedstock_dir, str):
        feedstock_dir = Path(feedstock_dir)

    if meta_yaml is None and recipe_yaml is None:
        raise ValueError("Either `meta_yaml` or  `recipe_yaml` needs to be given.")

    sub_graph.update({"feedstock_name": name, "parsing_error": False, "branch": "main"})

    if mark_not_archived:
        sub_graph.update({"archived": False})

    # strip out old keys - this removes old platforms when one gets disabled
    for key in list(sub_graph.keys()):
        if key.endswith("meta_yaml") or key.endswith("requirements") or key == "req":
            del sub_graph[key]

    if isinstance(meta_yaml, str):
        sub_graph["raw_meta_yaml"] = meta_yaml

    # Get the conda-forge.yml
    if isinstance(conda_forge_yaml, str):
        sub_graph["conda-forge.yml"] = {
            k: v for k, v in yaml.safe_load(conda_forge_yaml).items()
        }

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
                logger.debug(f"parsing conda-build config: {cbc_path}")
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

                # sometimes the requirements come out to None or [None]
                # and this ruins the aggregated meta_yaml / breaks stuff
                logger.debug(f"getting reqs for config: {cbc_path}")
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
                logger.debug(f"collapsing reqs for {name}")
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
            for k in set(sub_graph["conda-forge.yml"].get("provider", {})):
                if "_" in k:
                    plat_archs.append(tuple(k.split("_")))
            if isinstance(meta_yaml, str):
                variant_yamls = [
                    parse_meta_yaml(meta_yaml, platform=plat, arch=arch)
                    for plat, arch in plat_archs
                ]
    except Exception as e:
        import traceback

        trb = traceback.format_exc()
        sub_graph["parsing_error"] = f"make_graph: render error {e}\n{trb}"
        raise

    logger.debug("platforms: %s", plat_archs)
    sub_graph["platforms"] = ["_".join(k) for k in plat_archs]

    # this makes certain that we have consistent ordering
    sorted_variant_yamls = [x for _, x in sorted(zip(plat_archs, variant_yamls))]
    yaml_dict = ChainDB(*sorted_variant_yamls)
    if not yaml_dict:
        logger.error(f"Something odd happened when parsing recipe {name}")
        sub_graph["parsing_error"] = "make_graph: Could not parse"
        return sub_graph

    sub_graph["meta_yaml"] = _dedupe_meta_yaml(_convert_to_dict(yaml_dict))
    meta_yaml = sub_graph["meta_yaml"]

    # remove all plat-arch specific keys to remove old ones if a combination is disabled
    for k in list(sub_graph.keys()):
        if k in ["raw_meta_yaml", "total_requirements"]:
            continue
        if k.endswith("_meta_yaml") or k.endswith("_requirements"):
            sub_graph.pop(k)

    for k, v in zip(plat_archs, variant_yamls):
        plat_arch_name = "_".join(k)
        sub_graph[f"{plat_arch_name}_meta_yaml"] = v
        _, sub_graph[f"{plat_arch_name}_requirements"], _ = _extract_requirements(
            v,
            outputs_to_keep=BOOTSTRAP_MAPPINGS.get(name, None),
        )

    (
        sub_graph["total_requirements"],
        sub_graph["requirements"],
        sub_graph["strong_exports"],
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
        if "run" in sub_graph.get("meta_yaml", {}).get("requirements", {}):
            outputs_names.add(meta_yaml["package"]["name"])
    # add in single package name
    else:
        outputs_names = {meta_yaml["package"]["name"]}
    sub_graph["outputs_names"] = outputs_names

    # TODO: Write schema for dict
    # TODO: remove this
    req = _get_requirements(
        yaml_dict,
        outputs_to_keep=BOOTSTRAP_MAPPINGS.get(name, []),
    )
    sub_graph["req"] = req

    # set name and version
    keys = [("package", "name"), ("package", "version")]
    missing_keys = [k[1] for k in keys if k[1] not in yaml_dict.get(k[0], {})]
    for k in keys:
        if k[1] not in missing_keys:
            sub_graph[k[1]] = yaml_dict[k[0]][k[1]]

    # sometimes a version is not given at the top level, so we check outputs
    # we do not know which version to take, but hopefully they are all the same
    if (
        "version" not in sub_graph
        and "outputs" in yaml_dict
        and len(yaml_dict["outputs"]) > 0
        and "version" in yaml_dict["outputs"][0]
    ):
        sub_graph["version"] = yaml_dict["outputs"][0]["version"]

    # set the url and hash
    sub_graph.pop("url", None)
    sub_graph.pop("hash_type", None)

    source = yaml_dict.get("source", [])
    if isinstance(source, collections.abc.Mapping):
        source = [source]
    source_keys: Set[str] = set()
    for s in source:
        if not sub_graph.get("url"):
            sub_graph["url"] = s.get("url")
        source_keys |= s.keys()

    kl = list(sorted(source_keys & hashlib.algorithms_available, reverse=True))
    if kl:
        sub_graph["hash_type"] = kl[0]

    return sub_graph


def load_feedstock_local(
    name: str,
    sub_graph: typing.MutableMapping,
    meta_yaml: str | None = None,
    recipe_yaml: str | None = None,
    conda_forge_yaml: str | None = None,
    mark_not_archived: bool = False,
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
    """

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
                sub_graph.update(
                    {"feedstock_name": name, "parsing_error": False, "branch": "main"}
                )

                if mark_not_archived:
                    sub_graph.update({"archived": False})

                sub_graph["parsing_error"] = f"make_graph: {feedstock_dir.status_code}"
                return sub_graph

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

        populate_feedstock_attributes(
            name,
            sub_graph,
            meta_yaml=meta_yaml,
            recipe_yaml=recipe_yaml,
            conda_forge_yaml=conda_forge_yaml,
            mark_not_archived=mark_not_archived,
            feedstock_dir=feedstock_dir,
        )

    return sub_graph


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

    args = []

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

    data = run_container_task(
        "parse-feedstock",
        [
            "--existing-feedstock-node-attrs",
            "-",
            *args,
        ],
        json_loads=loads,
        input=json_blob,
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
        variable `CF_TICK_IN_CONTAINER` is 'false'. This feature can be
        used to avoid container in container calls.

    Returns
    -------
    sub_graph : MutableMapping
        The sub_graph, now updated with the feedstock metadata
    """
    in_container = os.environ.get("CF_TICK_IN_CONTAINER", "false") == "true"
    if use_container is None:
        use_container = not in_container

    if use_container and not in_container:
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
