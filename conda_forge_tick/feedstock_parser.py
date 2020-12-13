import collections.abc
import glob
import hashlib
import tempfile
import typing
import zipfile
import logging
from collections import defaultdict
import os
import re
from typing import Union, Set, Optional

import requests
import yaml

from requests.models import Response
from xonsh.lib.collections import _convert_to_dict, ChainDB

if typing.TYPE_CHECKING:
    from mypy_extensions import TestTypedDict
    from .migrators_types import PackageName, RequirementsTypedDict
    from conda_forge_tick.migrators_types import MetaYamlTypedDict

from .utils import as_iterable, parse_meta_yaml

LOGGER = logging.getLogger("conda_forge_tick.feedstock_parser")

PIN_SEP_PAT = re.compile(r" |>|<|=|\[")

CONDA_FORGE_YML_KEYS_TO_KEEP = (
    "provider",
    "min_r_ver",
    "min_py_ver",
    "max_py_ver",
    "max_r_ver",
    "compiler_stack",
    "bot",
)


def _get_requirements(
    meta_yaml: "MetaYamlTypedDict",
    outputs: bool = True,
    build: bool = True,
    host: bool = True,
    run: bool = True,
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


def _extract_requirements(meta_yaml):
    strong_exports = False
    requirements_dict = defaultdict(set)
    for block in [meta_yaml] + meta_yaml.get("outputs", []) or []:
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
    r = requests.get(
        f"https://github.com/conda-forge/{name}-feedstock/archive/master.zip",
    )
    if r.status_code != 200:
        LOGGER.error(
            f"Something odd happened when fetching feedstock {name}: {r.status_code}",
        )
        return r

    zname = os.path.join(dest, f"{name}-feedstock-master.zip")

    with open(zname, "wb") as fp:
        fp.write(r.content)

    z = zipfile.ZipFile(zname)
    z.extractall(path=dest)
    dest_dir = os.path.join(dest, os.path.split(z.namelist()[0])[0])
    return dest_dir


def populate_feedstock_attributes(
    name: str,
    sub_graph: typing.MutableMapping,
    meta_yaml: typing.Union[str, Response] = "",
    conda_forge_yaml: typing.Union[str, Response] = "",
    mark_not_archived=False,
    feedstock_dir=None,
) -> typing.MutableMapping:
    """Parse the various configuration information into something usable

    Notes
    -----
    If the return is bad hand the response itself in so that it can be parsed
    for meaning.
    """
    sub_graph.update({"feedstock_name": name, "bad": False, "branch": "master"})

    if mark_not_archived:
        sub_graph.update({"archived": False})

    # handle all the raw strings
    if isinstance(meta_yaml, Response):
        sub_graph["bad"] = f"make_graph: {meta_yaml.status_code}"
        return sub_graph

    # strip out old keys - this removes old platforms when one gets disabled
    for key in list(sub_graph.keys()):
        if key.endswith("meta_yaml") or key.endswith("requirements") or key == "req":
            del sub_graph[key]

    sub_graph["raw_meta_yaml"] = meta_yaml

    # Get the conda-forge.yml
    if isinstance(conda_forge_yaml, str):
        sub_graph["conda-forge.yml"] = {
            k: v
            for k, v in yaml.safe_load(conda_forge_yaml).items()
            if k in CONDA_FORGE_YML_KEYS_TO_KEEP
        }

    if feedstock_dir is not None:
        LOGGER.debug(
            "# of ci support files: %s",
            len(glob.glob(os.path.join(feedstock_dir, ".ci_support", "*.yaml"))),
        )

    try:
        if (
            feedstock_dir is not None
            and len(glob.glob(os.path.join(feedstock_dir, ".ci_support", "*.yaml"))) > 0
        ):
            recipe_dir = os.path.join(feedstock_dir, "recipe")
            ci_support_files = glob.glob(
                os.path.join(feedstock_dir, ".ci_support", "*.yaml"),
            )
            varient_yamls = []
            plat_arch = []
            for cbc_path in ci_support_files:
                cbc_name = os.path.basename(cbc_path)
                cbc_name_parts = cbc_name.replace(".yaml", "").split("_")
                plat = cbc_name_parts[0]
                if len(cbc_name_parts) == 1:
                    arch = "64"
                else:
                    if cbc_name_parts[1] in ["64", "aarch64", "ppc64le", "arm64"]:
                        arch = cbc_name_parts[1]
                    else:
                        arch = "64"
                plat_arch.append((plat, arch))

                varient_yamls.append(
                    parse_meta_yaml(
                        meta_yaml,
                        platform=plat,
                        arch=arch,
                        recipe_dir=recipe_dir,
                        cbc_path=cbc_path,
                    ),
                )

                # sometimes the requirements come out to None and this ruins the
                # aggregated meta_yaml
                if "requirements" in varient_yamls[-1]:
                    for section in ["build", "host", "run"]:
                        # We make sure to set a section only if it is actually in
                        # the recipe. Adding a section when it is not there might
                        # confuse migrators trying to move CB2 recipes to CB3.
                        if section in varient_yamls[-1]["requirements"]:
                            val = varient_yamls[-1]["requirements"].get(section, [])
                            varient_yamls[-1]["requirements"][section] = val or []

                # collapse them down
                final_cfgs = {}
                for plat_arch, varyml in zip(plat_arch, varient_yamls):
                    if plat_arch not in final_cfgs:
                        final_cfgs[plat_arch] = []
                    final_cfgs[plat_arch].append(varyml)
                for k in final_cfgs:
                    ymls = final_cfgs[k]
                    final_cfgs[k] = _convert_to_dict(ChainDB(*ymls))
                plat_arch = []
                varient_yamls = []
                for k, v in final_cfgs.items():
                    plat_arch.append(k)
                    varient_yamls.append(v)
        else:
            plat_arch = [("win", "64"), ("osx", "64"), ("linux", "64")]
            for k in set(sub_graph["conda-forge.yml"].get("provider", {})):
                if "_" in k:
                    plat_arch.append(k.split("_"))
            varient_yamls = [
                parse_meta_yaml(meta_yaml, platform=plat, arch=arch)
                for plat, arch in plat_arch
            ]
    except Exception as e:
        import traceback

        trb = traceback.format_exc()
        sub_graph["bad"] = f"make_graph: render error {e}\n{trb}"
        return sub_graph

    LOGGER.debug("platforms: %s", plat_arch)

    # this makes certain that we have consistent ordering
    sorted_varient_yamls = [x for _, x in sorted(zip(plat_arch, varient_yamls))]
    yaml_dict = ChainDB(*sorted_varient_yamls)
    if not yaml_dict:
        LOGGER.error(f"Something odd happened when parsing recipe {name}")
        sub_graph["bad"] = "make_graph: Could not parse"
        return sub_graph

    sub_graph["meta_yaml"] = _convert_to_dict(yaml_dict)
    meta_yaml = sub_graph["meta_yaml"]

    for k, v in zip(plat_arch, varient_yamls):
        plat_arch_name = "_".join(k)
        sub_graph[f"{plat_arch_name}_meta_yaml"] = v
        _, sub_graph[f"{plat_arch_name}_requirements"], _ = _extract_requirements(v)

    (
        sub_graph["total_requirements"],
        sub_graph["requirements"],
        sub_graph["strong_exports"],
    ) = _extract_requirements(meta_yaml)

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
    req = _get_requirements(yaml_dict)
    sub_graph["req"] = req

    # set name and version
    keys = [("package", "name"), ("package", "version")]
    missing_keys = [k[1] for k in keys if k[1] not in yaml_dict.get(k[0], {})]
    for k in keys:
        if k[1] not in missing_keys:
            sub_graph[k[1]] = yaml_dict[k[0]][k[1]]

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


def load_feedstock(
    name: str,
    sub_graph: typing.MutableMapping,
    meta_yaml: Optional[str] = None,
    conda_forge_yaml: Optional[str] = None,
    mark_not_archived: bool = False,
):
    """Load a feedstock into subgraph based on its name, if meta_yaml and
    conda_forge_yaml are provided

    Parameters
    ----------
    name : str
        Name of the feedstock
    sub_graph : MutableMapping
        The existing metadata if any
    meta_yaml : Optional[str]
        The string meta.yaml, overrides the file in the feedstock if provided
    conda_forge_yaml : Optional[str]
        The string conda-forge.yaml, overrides the file in the feedstock if provided
    mark_not_archived

    Returns
    -------
    sub_graph : MutableMapping
        The sub_graph, now updated with the feedstock metadata
    """
    # pull down one copy of the repo
    with tempfile.TemporaryDirectory() as tmpdir:
        feedstock_dir = _fetch_static_repo(name, tmpdir)

        if meta_yaml is None:
            if isinstance(feedstock_dir, Response):
                meta_yaml = feedstock_dir
            else:
                with open(os.path.join(feedstock_dir, "recipe", "meta.yaml")) as fp:
                    meta_yaml = fp.read()

        if conda_forge_yaml is None:
            if isinstance(feedstock_dir, Response):
                conda_forge_yaml = Response
            else:
                with open(os.path.join(feedstock_dir, "conda-forge.yml")) as fp:
                    conda_forge_yaml = fp.read()

        populate_feedstock_attributes(
            name,
            sub_graph,
            meta_yaml=meta_yaml,
            conda_forge_yaml=conda_forge_yaml,
            mark_not_archived=mark_not_archived,
            feedstock_dir=feedstock_dir,
        )
    return sub_graph
