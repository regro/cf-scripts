"""
Builds and maintains mapping of pypi-names to conda-forge names

1: Packages should be build from a `https://pypi.io/packages/` source
2: Packages MUST have a test: imports section importing it
"""

import glob
import sys
import yaml
import pathlib

from collections import Counter
from typing import Dict, List, Optional, Any
from os.path import commonprefix


from .utils import load, as_iterable


def load_node_meta_yaml(filename: str) -> Dict[str, str]:
    node_attr = load(open(filename))
    meta_yaml = node_attr.get("meta_yaml")
    return meta_yaml


def extract_pypi_name_from_metadata_extras(meta_yaml: Dict[str, Any]) -> Optional[str]:
    return meta_yaml.get("extra", {}).get("mappings", {}).get("python", {}).get("pypi")


def extract_pypi_name_from_metadata_source_url(
    meta_yaml: Dict[str, Any],
) -> Optional[str]:
    if "source" in meta_yaml:
        if "url" in meta_yaml["source"]:
            src_urls = meta_yaml["source"]["url"]
            src_urls = as_iterable(src_urls)
            for url in src_urls:
                if url.startswith("https://pypi.io/packages/") or url.startswith(
                    "https://pypi.org/packages/",
                ):
                    return url.split("/")[-2]
    return None


def extract_import_name_from_metadata_extras(
    meta_yaml: Dict[str, Any],
) -> Optional[str]:
    return (
        meta_yaml.get("extra", {})
        .get("mappings", {})
        .get("python", {})
        .get("import_name")
    )


def extract_import_name_from_test_imports(meta_yaml: Dict[str, Any]) -> Optional[str]:
    imports = meta_yaml.get("test", {}).get("imports", []) or []
    split_imports = [imp.split(".") for imp in imports]
    prefix = commonprefix(split_imports)
    # namespace common_prefixes
    #   strategy should cover the case for things like zope
    #       zope, zope.interface, zope.inferface.foo, zope.interface.bar
    c = Counter(len(imp) for imp in split_imports)
    if len(prefix) == 1 and c.get(1) == 1 and len(split_imports) > 3:
        ns_prefix = commonprefix([imp[1:] for imp in split_imports if len(imp) > 1])
        if prefix and ns_prefix:
            prefix = list(prefix) + list(ns_prefix)
        # print(prefix, ns_prefix)
    if prefix:
        return ".".join(prefix)
    return None


def extract_single_pypi_information(meta_yaml: Dict[str, Any]) -> Dict[str, str]:
    pypi_name = extract_pypi_name_from_metadata_extras(
        meta_yaml,
    ) or extract_pypi_name_from_metadata_source_url(meta_yaml)
    conda_name = meta_yaml["package"]["name"]
    import_name = extract_import_name_from_metadata_extras(
        meta_yaml,
    ) or extract_import_name_from_test_imports(meta_yaml)

    if import_name and conda_name and pypi_name:
        return {
            "pypi_name": pypi_name,
            "conda_name": conda_name,
            "import_name": import_name,
            "mapping_source": "regro-bot",
        }
    return {}


def extract_pypi_information(cf_graph: str) -> List[Dict[str, str]]:
    package_mappings = []
    for f in list(glob.glob(f"{cf_graph}/node_attrs/*.json")):
        meta_yaml = load_node_meta_yaml(f)
        if not meta_yaml:
            continue
        mapping = extract_single_pypi_information(meta_yaml)
        if mapping:
            package_mappings.append(mapping)

    return package_mappings


def convert_to_grayskull_style_yaml(
    package_mappings: List[Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    """Convert our list style mapping to the pypi-centric version required by grayskull
    """
    mismatch = [
        x
        for x in package_mappings
        if x["pypi_name"] != x.get("conda_name", x.get("conda_forge"))
    ]
    grayskull_fmt = {
        x["pypi_name"]: {k: v for k, v in x.items() if x != "pypi_name"}
        for x in sorted(mismatch, key=lambda x: x["pypi_name"])
        if x["pypi_name"] != x.get("conda_name", x.get("conda_forge"))
    }
    return grayskull_fmt


def load_static_mappings() -> List[Dict[str, str]]:
    path = pathlib.Path(__file__).parent / "pypi_name_mapping_static.yaml"
    with path.open("r") as fp:
        mapping = yaml.safe_load(fp)
    for d in mapping:
        d["mapping_source"] = "static"
    return mapping


def main(args: "CLIArgs") -> None:
    cf_graph = args.cf_graph
    static_packager_mappings = load_static_mappings()
    pypi_package_mappings = extract_pypi_information(cf_graph=cf_graph)
    grayskull_style = convert_to_grayskull_style_yaml(
        static_packager_mappings + pypi_package_mappings,
    )

    dirname = pathlib.Path(cf_graph) / "mappings" / "pypi"
    dirname.mkdir(parents=True, exist_ok=True)

    with (dirname / "grayskull_pypi_mapping.yaml").open("w") as fp:
        yaml.dump(grayskull_style, fp, default_flow_style=False, sort_keys=True)

    with (dirname / "name_mapping.yaml").open("w") as fp:
        yaml.dump(
            sorted(
                static_packager_mappings + pypi_package_mappings,
                key=lambda pkg: pkg.get("conda_name", pkg.get("conda_forge")),
            ),
            fp,
            default_flow_style=False,
            sort_keys=True,
        )


if __name__ == "__main__":
    # main()
    pass
