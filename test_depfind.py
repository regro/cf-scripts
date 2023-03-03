from depfinder.main import simple_import_to_pkg_map
from stdlib_list import stdlib_list
from conda_forge_tick.make_graph import COMPILER_STUBS_WITH_STRONG_EXPORTS
import requests

IGNORE_STUBS = ["doc", "example", "demo", "test", "unit_tests", "testing"]
IGNORE_TEMPLATES = ["*/{z}/*", "*/{z}s/*"]
DEPFINDER_IGNORE = []
for k in IGNORE_STUBS:
    for tmpl in IGNORE_TEMPLATES:
        DEPFINDER_IGNORE.append(tmpl.format(z=k))
DEPFINDER_IGNORE += ["*testdir/*", "*conftest*", "*/test.py", "*/versioneer.py"]

BUILTINS = set().union(
    # Some libs support older python versions, we don't want their std lib
    # entries in our diff though
    *[set(stdlib_list(k)) for k in ["2.7", "3.5", "3.6", "3.7", "3.8", "3.9"]]
)


STATIC_EXCLUDES = (
    {
        "python",
        "setuptools",
        "pip",
        "versioneer",
        # not a real dep
        "cross-python",
    }
    | BUILTINS
    | set(COMPILER_STUBS_WITH_STRONG_EXPORTS)
)
RANKINGS = []
for _ in range(10):
    r = requests.get(
        "https://raw.githubusercontent.com/regro/cf-graph-countyfair/master/ranked_hubs_authorities.json",
    )
    if r.status_code == 200:
        RANKINGS = r.json()
        break
del r


def extract_missing_packages(
    required_packages,
    questionable_packages,
    run_packages,
    node,
    python_nodes,
):
    exclude_packages = STATIC_EXCLUDES.union(
        {node, node.replace("-", "_"), node.replace("_", "-")},
    )

    d = {}
    cf_minus_df = set(run_packages)
    df_minus_cf = set()
    for import_name, supplying_pkgs in required_packages.items():
        print("imp|supply:", import_name, supplying_pkgs, flush=True)
        # If there is any overlap in the cf requirements and the supplying
        # pkgs remove from the cf_minus_df set
        overlap = supplying_pkgs & run_packages
        print("\toverlap:", overlap, flush=True)
        if overlap:
            # XXX: This is particularly annoying with clobbers
            cf_minus_df = cf_minus_df - overlap
        else:
            # TODO: sort by the rankings
            pkg_name = next(iter(k for k in RANKINGS if k in supplying_pkgs), None)
            if pkg_name:
                df_minus_cf.add(pkg_name)
            else:
                df_minus_cf.update(supplying_pkgs)
        print("\tcf_minus_df|df_minus_cf:", df_minus_cf, cf_minus_df, flush=True)

    for import_name, supplying_pkgs in questionable_packages.items():
        overlap = supplying_pkgs & run_packages
        if overlap:
            cf_minus_df = cf_minus_df - overlap

    # Only report for python nodes, we don't inspect for other deps
    if python_nodes is not None and python_nodes:
        cf_minus_df = (cf_minus_df - exclude_packages) & python_nodes
    if cf_minus_df:
        d.update(cf_minus_df=cf_minus_df)

    df_minus_cf = df_minus_cf - exclude_packages
    if df_minus_cf:
        d.update(df_minus_cf=df_minus_cf)
    return d


deps = simple_import_to_pkg_map(
    "praw-7.7.0",
    builtins=BUILTINS,
    ignore=DEPFINDER_IGNORE,
)
print("depfinder:", deps, flush=True)

dep_report = extract_missing_packages(
    deps["required"],
    deps["questionable"],
    set(),
    "praw",
    None,
)
print("dep report:", dep_report, flush=True)
