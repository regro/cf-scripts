"""
Builds and maintains mapping of pypi-names to conda-forge names

1: Packages should be build from a `https://pypi.io/packages/` source
2: Packages MUST have a test: imports section importing it
"""

import glob

import requests
import yaml
import pathlib
import functools

from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any, Tuple, Set, Iterable
from os.path import commonprefix


from .utils import load, as_iterable, load_graph, dump, loads


def load_node_meta_yaml(filename: str) -> Optional[Dict[str, str]]:
    node_attr = load(open(filename))
    if node_attr.get("archived", False):
        return None
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
                if (
                    url.startswith("https://pypi.io/packages/")
                    or url.startswith("https://pypi.org/packages/")
                    or url.startswith("https://pypi.python.org/packages/")
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


_KNOWN_NAMESPACE_PACKAGES: List[str] = [
    "azure",
    "backports",
    "bob",
    "eolearn",
    "flaskext",
    "google",
    "google.cloud",
    "jaraco",
    "sphinxcontrib",
    "vaex",
    "zope",
]

KNOWN_NAMESPACE_PACKAGES: Set[str] = {
    tuple(imp.split(".")) for imp in _KNOWN_NAMESPACE_PACKAGES
}


def _imports_to_canonical_import(
    split_imports: Set[Tuple[str, ...]],
    parent_prefix=(),
) -> Tuple[str, ...]:
    """Extract the canonical import name from a list of imports

    We have two rules.

    1. If you have at least 4 imports and they follow a structure like
        'a', 'a.b', 'a.b.c', 'a.b.d'
        this is treated as a namespace package with a canonical import of `a.b`
    2. If you have fewer imports but they have a prefix that is found in
        KNOWN_NAMESPACE_PACKAGES
        you are also treated as a namespace package
    3. Otherwise return the commonprefix

    """
    prefix: Tuple[str, ...] = commonprefix(list(split_imports))
    c = Counter(len(imp) for imp in split_imports)
    if (
        len(prefix) == 1
        and c.get(1) == 1
        and (
            (len(split_imports) > 3)
            or (parent_prefix + prefix in KNOWN_NAMESPACE_PACKAGES)
        )
    ):
        ns_prefix = _imports_to_canonical_import(
            split_imports={imp[1:] for imp in split_imports if len(imp) > 1},
            parent_prefix=parent_prefix + prefix,
        )
        if prefix and ns_prefix:
            return prefix + ns_prefix
    return prefix


def imports_to_canonical_import(imports: Set[str]) -> str:
    import_tuple = _imports_to_canonical_import(
        {tuple(imp.split(".")) for imp in imports},
    )
    return ".".join(import_tuple)


def extract_import_name_from_test_imports(meta_yaml: Dict[str, Any]) -> Optional[str]:
    imports = set(meta_yaml.get("test", {}).get("imports", []) or [])
    return imports_to_canonical_import(imports)


def extract_single_pypi_information(meta_yaml: Dict[str, Any]) -> Dict[str, str]:
    pypi_name = (
        extract_pypi_name_from_metadata_extras(
            meta_yaml,
        )
        or extract_pypi_name_from_metadata_source_url(meta_yaml)
    )
    conda_name = meta_yaml["package"]["name"]
    import_name = (
        extract_import_name_from_metadata_extras(
            meta_yaml,
        )
        or extract_import_name_from_test_imports(meta_yaml)
    )

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
    # TODO: exclude archived node_attrs
    for f in list(glob.glob(f"{cf_graph}/node_attrs/*.json")):
        meta_yaml = load_node_meta_yaml(f)
        if meta_yaml is None:
            continue
        if not meta_yaml:
            continue
        mapping = extract_single_pypi_information(meta_yaml)
        if mapping:
            package_mappings.append(mapping)

    return package_mappings


def convert_to_grayskull_style_yaml(
    package_mappings: Iterable[Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    """Convert our list style mapping to the pypi-centric version
    required by grayskull"""
    mismatch = [
        x
        for x in package_mappings
        if (x["pypi_name"] != x["conda_name"] or x["pypi_name"] != x["import_name"])
    ]
    grayskull_fmt = {
        x["pypi_name"]: {k: v for k, v in x.items() if x != "pypi_name"}
        for x in sorted(mismatch, key=lambda x: x["pypi_name"])
    }
    return grayskull_fmt


def load_static_mappings() -> List[Dict[str, str]]:
    path = pathlib.Path(__file__).parent / "pypi_name_mapping_static.yaml"
    with path.open("r") as fp:
        mapping = yaml.safe_load(fp)
    for d in mapping:
        d["mapping_source"] = "static"
    return mapping


def determine_best_matches_for_pypi_import(
    mapping: List[Dict[str, Any]],
    cf_graph: str,
):
    map_by_import_name = defaultdict(set)
    map_by_conda_name = dict()
    final_map = {}
    ordered_import_names = []

    for m in mapping:
        # print(m)
        conda_name = m["conda_name"]
        map_by_import_name[m["import_name"]].add(conda_name)
        map_by_conda_name[conda_name] = m

    graph_file = str(pathlib.Path(cf_graph) / "graph.json")
    gx = load_graph(graph_file)
    # TODO: filter out archived feedstocks?

    try:
        clobberers = loads(
            requests.get(
                "https://raw.githubusercontent.com/regro/libcfgraph/master/"
                "clobbering_pkgs.json",
            ).text,
        )
    except Exception as e:
        print(e)
        clobberers = set()
    import networkx

    # computes hubs and authorities.
    # hubs are centralized sources (eg numpy)
    # whilst authorities are packages with many edges to them.
    hubs, authorities = networkx.hits_scipy(gx)

    mapping_src_weights = {
        "static": 1,
        "regro-bot": 2,
        "other": 3,
    }

    def _score(conda_name, conda_name_is_feedstock_name=True, pkg_clobbers=False):
        """A higher score means less preferred"""
        mapping_src = map_by_conda_name.get(conda_name, {}).get(
            "mapping_source", "other"
        )
        mapping_src_weight = mapping_src_weights.get(mapping_src, 99)
        return (
            # prefer static mapped packages over inferred
            mapping_src_weight,
            int(pkg_clobbers),
            # A higher hub score means more centrality in the graph
            -hubs.get(conda_name, 0),
            # A lower authority score means fewer dependencies
            authorities.get(conda_name, 0),
            # prefer pkgs that match feedstocks
            -int(conda_name_is_feedstock_name),
            conda_name,
        )

    def score(pkg_name):
        """Base the score on

        Packages that are hubs are preferred.
        In the event of ties, fall back to the one with the lower authority score
        which means in this case, fewer dependencies
        """
        conda_names = gx.graph["outputs_lut"].get(pkg_name, {pkg_name})
        return min(
            _score(
                conda_name,
                conda_name_is_feedstock_name=(conda_name == pkg_name),
                pkg_clobbers=pkg_name in clobberers,
            )
            for conda_name in conda_names
        )

    pkgs = list(gx.graph["outputs_lut"])
    ranked_list = list(sorted(pkgs, key=score))
    with open(pathlib.Path(cf_graph) / "ranked_hubs_authorities.json", "w") as f:
        dump(ranked_list, f)

    for import_name, candidates in sorted(map_by_import_name.items()):
        if len(candidates) > 1:
            ranked_candidates = list(sorted(candidates, key=score))
            winner = ranked_candidates[0]
            print(f"needs {import_name} <- provided_by: {candidates} : chosen {winner}")
            final_map[import_name] = map_by_conda_name[winner]
            ordered_import_names.append(
                {
                    "import_name": import_name,
                    "ranked_conda_names": reversed(ranked_candidates),
                },
            )
        else:
            candidate = list(candidates)[0]
            final_map[import_name] = map_by_conda_name[candidate]
            ordered_import_names.append(
                {"import_name": import_name, "ranked_conda_names": [candidate]},
            )

    return final_map, ordered_import_names


def main(args: "CLIArgs") -> None:
    cf_graph = args.cf_graph
    static_packager_mappings = load_static_mappings()
    pypi_package_mappings = extract_pypi_information(cf_graph=cf_graph)
    best_imports, ordered_import_names = determine_best_matches_for_pypi_import(
        cf_graph=cf_graph,
        mapping=pypi_package_mappings + static_packager_mappings,
    )

    grayskull_style = convert_to_grayskull_style_yaml(best_imports.values())

    dirname = pathlib.Path(cf_graph) / "mappings" / "pypi"
    dirname.mkdir(parents=True, exist_ok=True)

    yaml_dump = functools.partial(yaml.dump, default_flow_style=False, sort_keys=True)

    with (dirname / "grayskull_pypi_mapping.yaml").open("w") as fp:
        yaml_dump(grayskull_style, fp)

    with (dirname / "name_mapping.yaml").open("w") as fp:
        yaml_dump(
            sorted(
                static_packager_mappings + pypi_package_mappings,
                key=lambda pkg: pkg["conda_name"],
            ),
            fp,
        )

    with (dirname / "import_name_priority_mapping.yaml").open("w") as fp:
        yaml_dump(
            sorted(ordered_import_names, key=lambda entry: entry["import_name"]),
            fp,
        )


if __name__ == "__main__":
    # main()
    pass
