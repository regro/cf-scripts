"""
Builds and maintains mapping of pypi-names to conda-forge names

1: Packages should be build from a `https://pypi.io/packages/` source
2: Packages MUST have a test: imports section importing it
"""

import glob
import sys
import yaml
import pathlib

from typing import Dict, List


from .utils import load, as_iterable


def load_node_meta_yaml(filename: str) -> Dict[str, str]:
    node_attr = load(open(filename))
    meta_yaml = node_attr.get("meta_yaml")
    return meta_yaml


def extract_single_pypi_information(meta_yaml: Dict[str, str]) -> Dict[str, str]:
    if "source" in meta_yaml:
        if "url" in meta_yaml["source"]:
            src_urls = meta_yaml["source"]["url"]
            src_urls = as_iterable(src_urls)
            for url in src_urls:
                if url.startswith("https://pypi.io/packages/") or url.startswith("https://pypi.org/packages/"):
                    break
            else:
                return {}

            # now get the name
            conda_name = meta_yaml["package"]["name"]
            pypi_name = url.split("/")[-2]
            # determine the import_name
            imports = meta_yaml.get("test", {}).get("imports", []) or []
            imports = {x for x in imports if "." not in x}
            if len(imports) == 1:
                import_name = list(imports)[0]
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
        package_mappings.append(extract_single_pypi_information(meta_yaml))

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
        yaml.dump(grayskull_style, fp, default_flow_style=True, sort_keys=True)

    with (dirname / "name_mapping.yaml").open("w") as fp:
        yaml.dump(
            sorted(
                static_packager_mappings + pypi_package_mappings,
                key=lambda pkg: pkg.get("conda_name", pkg.get("conda_forge")),
            ),
            fp,
            default_flow_style=True,
            sort_keys=True,
        )


if __name__ == "__main__":
    # main()
    pass
