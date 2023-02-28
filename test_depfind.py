from depfinder.main import simple_import_to_pkg_map
from stdlib_list import stdlib_list


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


print(
    simple_import_to_pkg_map(
        "praw-7.7.0",
        builtins=BUILTINS,
        ignore=DEPFINDER_IGNORE,
    ),
    flush=True,
)
