"""
Builds and maintains mapping of pypi-names to conda-forge names.

1: Packages should be build from a `https://pypi.io/packages/` source
2: Packages MUST have a test: imports section importing it
"""

import functools
import math
import os
import pathlib
import traceback
from collections import Counter, defaultdict
from collections.abc import Collection
from os.path import commonprefix
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, TypedDict, Union

import orjson
import requests
import yaml
from packaging.utils import NormalizedName as PypiName
from packaging.utils import canonicalize_name as canonicalize_pypi_name

from .import_to_pkg import IMPORT_TO_PKG_DIR_CLOBBERING
from .lazy_json_backends import (
    CF_TICK_GRAPH_DATA_BACKENDS,
    LazyJson,
    dump,
    get_all_keys_for_hashmap,
    loads,
)
from .settings import settings
from .utils import as_iterable, load_existing_graph


class Mapping(TypedDict):
    pypi_name: PypiName
    conda_name: str
    import_name: str
    mapping_source: str


def load_node_meta_yaml(node: str) -> Optional[Dict[str, str]]:
    node_attr = LazyJson(f"node_attrs/{node}.json")
    if node_attr.get("archived", False):
        return None
    meta_yaml = node_attr.get("meta_yaml", None)
    return meta_yaml


def extract_pypi_name_from_metadata_extras(
    meta_yaml: Dict[str, Any],
) -> Optional[PypiName]:
    raw = meta_yaml.get("extra", {}).get("mappings", {}).get("python", {}).get("pypi")
    if raw is not None:
        return canonicalize_pypi_name(raw)
    return None


def extract_pypi_name_from_metadata_source_url(
    meta_yaml: Dict[str, Any],
) -> Optional[PypiName]:
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
                    return canonicalize_pypi_name(url.split("/")[-2])
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

KNOWN_NAMESPACE_PACKAGES: Set[Tuple[str, ...]] = {
    tuple(imp.split(".")) for imp in _KNOWN_NAMESPACE_PACKAGES
}


def _imports_to_canonical_import(
    split_imports: Set[Tuple[str, ...]],
    parent_prefix=(),
) -> Union[Tuple[str, ...], Literal[""]]:
    """Extract the canonical import name from a list of imports.

    We have two rules.

    1. If you have at least 4 imports and they follow a structure like
        'a', 'a.b', 'a.b.c', 'a.b.d'
        this is treated as a namespace package with a canonical import of `a.b`
    2. If you have fewer imports but they have a prefix that is found in
        KNOWN_NAMESPACE_PACKAGES
        you are also treated as a namespace package
    3. Otherwise return the commonprefix

    """
    prefix: Union[Tuple[str, ...], Literal[""]] = commonprefix(list(split_imports))  # type: ignore
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


def extract_single_pypi_information(meta_yaml: Dict[str, Any]) -> Optional[Mapping]:
    pypi_name = extract_pypi_name_from_metadata_extras(
        meta_yaml,
    ) or extract_pypi_name_from_metadata_source_url(meta_yaml)
    conda_name = meta_yaml["package"]["name"]
    import_name = extract_import_name_from_metadata_extras(
        meta_yaml,
    ) or extract_import_name_from_test_imports(meta_yaml)

    if import_name and conda_name and pypi_name:
        return Mapping(
            pypi_name=pypi_name,
            conda_name=conda_name,
            import_name=import_name,
            mapping_source="regro-bot",
        )
    return None


def extract_pypi_information() -> List[Mapping]:
    package_mappings: List[Mapping] = []
    nodes = get_all_keys_for_hashmap("node_attrs")
    for node in nodes:
        meta_yaml = load_node_meta_yaml(node)
        if meta_yaml is None:
            continue
        if not meta_yaml:
            continue
        mapping = extract_single_pypi_information(meta_yaml)
        if mapping is not None:
            package_mappings.append(mapping)

    return package_mappings


def convert_to_grayskull_style_yaml(
    best_imports: Dict[str, Mapping],
) -> Dict[PypiName, Mapping]:
    """Convert our list style mapping to the pypi-centric version
    required by grayskull by reindexing on the PyPI name.
    """
    package_mappings = best_imports.values()
    sorted_mappings = sorted(package_mappings, key=lambda mapping: mapping["pypi_name"])

    grayskull_fmt: Dict[PypiName, Mapping] = {}
    for mapping in sorted_mappings:
        pypi_name = mapping["pypi_name"]
        if pypi_name not in grayskull_fmt:
            grayskull_fmt[pypi_name] = mapping
        else:
            # This is an exceptional case where the same PyPI package name has two
            # different import names. For example, the PyPI package ruamel.yaml is
            # provided also by a conda-forge package named ruamel_yaml.
            collisions = [
                mapping
                for mapping in package_mappings
                if mapping["pypi_name"] == pypi_name
            ]
            grayskull_fmt[pypi_name] = resolve_collisions(collisions)
    return grayskull_fmt


def add_missing_pypi_names(
    pypi_mapping: Dict[PypiName, Mapping],
    mappings: List[Mapping],
    overrides: List[Mapping],
) -> Dict[PypiName, Mapping]:
    """Add missing PyPI names to the Grayskull mapping.

    The `convert_to_grayskull_style_yaml` function reindexes from the import name
    to the PyPI name. In case there are multiple PyPI names for a given import name,
    only the winner is represented in the resulting Grayskull mapping. This function
    adds the missing PyPI names back in.
    """
    unsorted_mapping: Dict[PypiName, Mapping] = pypi_mapping.copy()
    missing_mappings_by_pypi_name: Dict[PypiName, List[Mapping]] = defaultdict(list)
    for mapping in mappings:
        pypi_name = mapping["pypi_name"]
        if pypi_name not in unsorted_mapping:
            missing_mappings_by_pypi_name[mapping["pypi_name"]].append(mapping)
    # Always add in the overrides
    for mapping in overrides:
        pypi_name = mapping["pypi_name"]
        missing_mappings_by_pypi_name[mapping["pypi_name"]].append(mapping)

    for pypi_name, candidates in missing_mappings_by_pypi_name.items():
        unsorted_mapping[pypi_name] = resolve_collisions(candidates)
    return dict(sorted(unsorted_mapping.items()))


def resolve_collisions(collisions: List[Mapping]) -> Mapping:
    """Given a list of colliding mappings, try to resolve the collision
    by picking out the unique mapping whose source is from the static mappings file.
    If there is a problem, then make a guess, print a warning, and continue.

    Raises
    ------
    ValueError
        If there are no collisions to resolve.
    """
    if len(collisions) == 0:
        raise ValueError("No collisions to resolve!")
    if len(collisions) == 1:
        return collisions[0]
    assert len(collisions) >= 2
    statics = [
        collision for collision in collisions if collision["mapping_source"] == "static"
    ]
    if len(statics) == 1:
        return statics[0]

    print("WARNING!!!")
    print(traceback.format_stack()[-2])
    if len(statics) == 0:
        print(
            f"Could not resolve the following collisions: {collisions}. "
            f"Please define a static mapping to break the tie.",
        )
        return collisions[-1]
    else:
        assert len(statics) > 1
        print(f"Conflicting statically sourced packages {statics}.")
        return statics[-1]


def load_static_mappings() -> List[Mapping]:
    path = pathlib.Path(__file__).parent / "pypi_name_mapping_static.yaml"
    with path.open("r") as fp:
        mapping = yaml.safe_load(fp)
    for d in mapping:
        d["mapping_source"] = "static"
        d["pypi_name"] = canonicalize_pypi_name(d["pypi_name"])
    return mapping


def chop(x: float) -> float:
    """Chop the mantissa of a float to 20 bits.

    This helps to alleviate floating point arithmetic errors when sorting by float keys.
    """
    if isinstance(x, int):
        return x
    m, e = math.frexp(x)
    m = round(m * (2 << 20)) / (2 << 20)
    return m * 2**e


def determine_best_matches_for_pypi_import(
    mapping: List[Mapping],
) -> Tuple[Dict[str, Mapping], List[Dict]]:
    map_by_import_name: Dict[str, List[Mapping]] = defaultdict(list)
    map_by_conda_name: Dict[str, Mapping] = dict()
    final_map: Dict[str, Mapping] = {}
    ordered_import_names: List[Dict] = []

    for m in mapping:
        # print(m)
        conda_name = m["conda_name"]
        map_by_import_name[m["import_name"]].append(m)
        map_by_conda_name[conda_name] = m

    graph_file = str(pathlib.Path(".") / "graph.json")
    gx = load_existing_graph(graph_file)
    # TODO: filter out archived feedstocks?

    clobberers: Collection
    try:
        if "file" in CF_TICK_GRAPH_DATA_BACKENDS and os.path.exists(
            IMPORT_TO_PKG_DIR_CLOBBERING
        ):
            with open(IMPORT_TO_PKG_DIR_CLOBBERING) as fp:
                clobberers = loads(fp.read())
        else:
            clobberers = loads(
                requests.get(
                    os.path.join(
                        settings().graph_github_backend_raw_base_url,
                        IMPORT_TO_PKG_DIR_CLOBBERING,
                    )
                ).text,
            )
    except Exception as e:
        print(e)
        clobberers = set()
    import networkx

    # computes hubs and authorities.
    # hubs are centralized sources (eg numpy)
    # whilst authorities are packages with many edges to them.
    hubs, authorities = networkx.hits(gx)

    # Some hub/authority values are in the range +/- 1e-20. Clip these to 0.
    # (There are no values between 1e-11 and 1e-19.)
    hubs = {k: v if v > 1e-15 else 0 for k, v in hubs.items()}
    authorities = {k: v if v > 1e-15 else 0 for k, v in authorities.items()}

    mapping_src_weights = {
        "static": 1,
        "regro-bot": 2,
        "other": 3,
    }

    def _score(conda_name, conda_name_is_feedstock_name=True, pkg_clobbers=False):
        """Get the score.
        A higher score means less preferred.
        """
        mapping_src = map_by_conda_name.get(conda_name, {}).get(  # type: ignore[call-overload]
            "mapping_source",
            "other",
        )
        mapping_src_weight = mapping_src_weights.get(mapping_src, 99)
        return (
            # prefer static mapped packages over inferred
            mapping_src_weight,
            int(pkg_clobbers),
            # A higher hub score means more centrality in the graph
            -chop(hubs.get(conda_name, 0)),
            # A lower authority score means fewer dependencies
            chop(authorities.get(conda_name, 0)),
            # prefer pkgs that match feedstocks
            -int(conda_name_is_feedstock_name),
            conda_name,
        )

    def score(pkg_name):
        """Score a package name.

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
    with open(pathlib.Path(".") / "ranked_hubs_authorities.json", "w") as f:
        dump(ranked_list, f)

    for import_name, candidates in sorted(map_by_import_name.items()):
        conda_names = {c["conda_name"] for c in candidates}
        ranked_conda_names = list(sorted(conda_names, key=score))
        winning_name = ranked_conda_names[0]
        if len(ranked_conda_names) > 1:
            print(
                f"needs {import_name} <- provided_by: {ranked_conda_names} : "
                f"chosen {winning_name}",
            )
        # Due to concatenating the graph mapping and the static mapping, there might
        # be multiple candidates with the same conda_name but different PyPI names.
        winning_candidates = [c for c in candidates if c["conda_name"] == winning_name]
        winner = resolve_collisions(winning_candidates)
        final_map[import_name] = winner
        ordered_import_names.append(
            {
                "import_name": import_name,
                "ranked_conda_names": list(reversed(ranked_conda_names)),
            },
        )
    return final_map, ordered_import_names


def main() -> None:
    # Statically defined mappings from pypi_name_mapping_static.yaml
    static_package_mappings: List[Mapping] = load_static_mappings()

    # Mappings extracted from the graph
    pypi_package_mappings: List[Mapping] = extract_pypi_information()

    # best_imports is indexed by import_name.
    best_imports, ordered_import_names = determine_best_matches_for_pypi_import(
        mapping=pypi_package_mappings + static_package_mappings,
    )

    grayskull_style_from_imports = convert_to_grayskull_style_yaml(best_imports)
    grayskull_style = add_missing_pypi_names(
        grayskull_style_from_imports,
        pypi_package_mappings,
        static_package_mappings,
    )

    dirname = pathlib.Path(".") / "mappings" / "pypi"
    dirname.mkdir(parents=True, exist_ok=True)

    yaml_dump = functools.partial(yaml.dump, default_flow_style=False, sort_keys=True)

    def json_dump(obj, fp):
        fp.write(
            orjson.dumps(obj, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2).decode(
                "utf-8"
            )
        )

    # import pdb; pdb.set_trace()
    for dumper, suffix in ((yaml_dump, "yaml"), (json_dump, "json")):
        with (dirname / f"grayskull_pypi_mapping.{suffix}").open("w") as fp:
            dumper(grayskull_style, fp)

        with (dirname / f"name_mapping.{suffix}").open("w") as fp:
            dumper(
                sorted(
                    static_package_mappings + pypi_package_mappings,
                    key=lambda pkg: pkg["conda_name"],
                ),
                fp,
            )

        with (dirname / f"import_name_priority_mapping.{suffix}").open("w") as fp:
            dumper(
                sorted(ordered_import_names, key=lambda entry: entry["import_name"]),
                fp,
            )
