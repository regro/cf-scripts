import json
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from conda_forge_tick.lazy_json_backends import get_sharded_path
from conda_forge_tick.models.node_attributes import NodeAttributes
from conda_forge_tick.models.pr_info import PrInfo
from conda_forge_tick.models.pr_json import PullRequestData
from conda_forge_tick.models.version_pr_info import VersionPrInfo
from conda_forge_tick.models.versions import Versions

"""
These tests validate that the node attributes files in the node_attrs directory are valid JSON and
conform to the NodeAttributes schema.

Since we currently do not use the NodeAttributes schema in production, and also do not enforce some rules
in the conda-smithy linter (e.g. valid URLs in , it is very possible that failures in these tests can occur.

The most likely cause of these failures is that the meta.yaml file of an upstream feedstock does not conform to
the MetaYaml schema - note that some fields of the NodeAttributes schema are derived directly from the meta.yaml file.

You can add the name of a feedstock to the KNOWN_BAD_FEEDSTOCKS list if you know that it will fail these tests.
After fixing the issue, you can remove the feedstock from the list.
"""

NODE_ATTRS_BAD_FEEDSTOCKS = {
    "gmatelastoplasticqpot3d",  # missing platforms
    "thrust",  # missing platforms
    "cub",  # missing platforms
    "birka",  # outdated version field in dependency graph (package.version field removed in meta.yaml)
    "xsimd",  # recipe/meta.yaml about.doc_url has a typo in the URL scheme
    "anyqt",  # recipe/meta.yaml about.dev_url has a typo in the URL scheme
    "condastats",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "pytermgui",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "torcpy",  # recipe/meta.yaml about.dev_url has typo
    "scikit-plot",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "matbench-genmetrics",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "neutronics_material_maker",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "gulp",  # recipe/meta.yaml about.dev_url has invalid URL scheme
    "wagtail-bakery",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "mp_time_split",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "shippinglabel",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "cddlib",  # recipe/meta.yaml about.doc_url has "ftp" URL scheme (and is unreachable)
    "everett",  # recipe/meta.yaml about.dev_url has invalid URL scheme
    "scheil",  # recipe/meta.yaml about.doc_url is not a valid URL
    "llspy-slm",  # recipe/meta.yaml about.doc_url has invalid URL scheme
    "path.py",  # build.noarch: true in meta.yaml, which should probably be build.noarch: python
    "sparc-x",  # `conda-forge.yml`.channels is unexpected
    "bamnostic",  # unrecognized field `conda-forge.yml`.build
    "pyrosm",  # unrecognized option `conda-forge.yml`.build, legacy field `conda-forge.yml`.matrix does not validate
    "sketchnu",  # `conda-forge.yml`.conda_build.pkg_format may not be None
    "sense2vec",  # `conda-forge.yml`.channels is unexpected
    "rpaframework",  # `conda-forge.yml`.channel_priority has invalid value "False"
    # see https://github.com/conda-forge/conda-smithy/issues/1863 for the top-level build platform fields
    "libtk",  # `conda-forge.yml`.linux_ppc64le and linux_aarch64 should be removed (see above)
    "pnab",  # missing build number in the recipe/meta.yaml
}

PR_INFO_BAD_FEEDSTOCKS = {
    "python",  # pr_info (bot internal): PR.data.branch should be string, not float
    "font-ttf-noto-emoji",  # PRed.0.data.version is not a valid conda version
}

VERSION_PR_INFO_BAD_FEEDSTOCKS = {}


@dataclass
class PerPackageModel:
    base_path: Path
    model: TypeAdapter
    bad_feedstocks: set[str] = field(default_factory=set)
    must_exist: bool = True
    """
    If True, the feedstock must exist in the base_path directory.
    """

    @property
    def __name__(self):
        return str(self.base_path.name)


PER_PACKAGE_MODELS: list[PerPackageModel] = [
    PerPackageModel(Path("node_attrs"), NodeAttributes, NODE_ATTRS_BAD_FEEDSTOCKS),
    PerPackageModel(Path("pr_info"), PrInfo, PR_INFO_BAD_FEEDSTOCKS),
    PerPackageModel(Path("versions"), Versions, must_exist=False),
    PerPackageModel(
        Path("version_pr_info"), VersionPrInfo, VERSION_PR_INFO_BAD_FEEDSTOCKS
    ),
]


def get_all_feedstocks() -> set[str]:
    packages: set[str] = set()

    for model in PER_PACKAGE_MODELS:
        for file in model.base_path.rglob("*.json"):
            packages.add(file.stem)

    return packages


def pytest_generate_tests(metafunc):
    packages = get_all_feedstocks()

    if not packages:
        warnings.warn(
            "No packages found. Make sure these tests are run "
            "from within the cf-graph-countyfair repository in order to do full "
            "schema validation."
        )

    all_invalid_feedstocks = set()
    for model in PER_PACKAGE_MODELS:
        all_invalid_feedstocks.update(model.bad_feedstocks)

    nonexistent_bad_feedstocks = all_invalid_feedstocks - packages

    if nonexistent_bad_feedstocks:
        warnings.warn(
            f"Some feedstocks are mentioned as bad feedstock but do not exist: {nonexistent_bad_feedstocks}"
        )

    if "valid_feedstock" in metafunc.fixturenames:
        parameters: list[tuple[PerPackageModel, str]] = []
        for model in PER_PACKAGE_MODELS:
            for package in packages:
                if package not in model.bad_feedstocks:
                    parameters.append((model, package))

        metafunc.parametrize(
            "model,valid_feedstock",
            parameters,
        )
        return

    if "invalid_feedstock" in metafunc.fixturenames:
        parameters: list[tuple[PerPackageModel, str]] = []
        for model in PER_PACKAGE_MODELS:
            for package in packages:
                if package in model.bad_feedstocks:
                    parameters.append((model, package))

        metafunc.parametrize(
            "model,invalid_feedstock",
            parameters,
        )

    if "pr_json" in metafunc.fixturenames:
        name_list: list[str] = []
        pr_json_list: list[str] = []
        for file in Path("pr_json").rglob("*.json"):
            with open(file) as f:
                name_list.append(file.stem)
                pr_json_list.append(f.read())

        metafunc.parametrize(
            "pr_json",
            pr_json_list,
            ids=name_list,
        )


def test_model_valid(model: PerPackageModel, valid_feedstock: str):
    try:
        node_attrs_pth = get_sharded_path(f"node_attrs/{valid_feedstock}.json")
        with open(node_attrs_pth) as f:
            node_attrs = f.read()
        data = json.loads(node_attrs)
    except FileNotFoundError:
        data = None

    if data is not None and data.get("archived", False):
        pytest.xfail("archived feedstocks need not be valid")

    path = get_sharded_path(model.base_path / f"{valid_feedstock}.json")
    try:
        with open(path) as f:
            node_attrs = f.read()
    except FileNotFoundError:
        if model.must_exist:
            raise
        pytest.skip(f"{path} does not exist")

    if (
        data is not None
        and model.model is NodeAttributes
        and (data.get("meta_yaml", {}) or {}).get("schema_version", 0) == 1
    ):
        pytest.xfail("recipes using schema version 1 cannot yet be validated")

    model.model.validate_json(node_attrs)


def test_model_invalid(model: PerPackageModel, invalid_feedstock: str):
    path = get_sharded_path(model.base_path / f"{invalid_feedstock}.json")
    try:
        with open(path) as f:
            node_attrs = f.read()
    except FileNotFoundError:
        if model.must_exist:
            raise
        pytest.skip(f"{path} does not exist")

    with pytest.raises(ValidationError):
        model.model.validate_json(node_attrs)


def test_validate_pr_json(pr_json: str):
    TypeAdapter(PullRequestData).validate_json(pr_json)
