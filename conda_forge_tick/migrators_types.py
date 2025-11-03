import typing
from typing import List, Literal, TypedDict, Union

PackageName = typing.NewType("PackageName", str)


class AboutTypedDict(TypedDict, total=False):
    description: str
    dev_url: str
    doc_url: str
    home: str
    license: str
    license_family: str
    license_file: str
    summary: str


# PRStateOpen: Literal["open"]
# PRStateClosed: Literal["closed"]
# PRStateMerged: Literal["merged"]

# PRState = Literal[PRStateClosed, PRStateMerged, PRStateOpen]
PRState = typing.NewType("PRState", str)


class PRHead_TD(TypedDict, total=False):
    ref: str


class PR_TD(TypedDict, total=False):
    state: PRState
    head: PRHead_TD


class BlasRebuildMigrateTypedDict(TypedDict):
    bot_rerun: bool
    migrator_name: str
    migrator_version: int
    name: str


class BuildRunExportsDict(TypedDict, total=False):
    strong: List[PackageName]
    weak: List[PackageName]


class BuildTypedDict(TypedDict, total=False):
    noarch: str
    number: str
    script: str
    run_exports: list[PackageName] | BuildRunExportsDict


ExtraTypedDict = TypedDict("ExtraTypedDict", {"recipe-maintainers": List[str]})


# class HTypedDict(TypedDict):
#     data: 'DataTypedDict'
#     keys: List[str]


class MetaYamlOutputs(TypedDict, total=False):
    name: str
    requirements: "RequirementsTypedDict"
    test: "TestTypedDict"
    # TODO: Not entirely sure this is right
    build: BuildTypedDict


class RecipeTypedDict(TypedDict, total=False):
    about: "AboutTypedDict"
    build: "BuildTypedDict"
    extra: "ExtraTypedDict"
    package: "PackageTypedDict"
    requirements: "RequirementsTypedDict"
    source: "SourceTypedDict"
    test: "TestTypedDict"
    outputs: List[MetaYamlOutputs]
    schema_version: int


class MigrationUidTypedDict(TypedDict, total=False):
    already_done: bool
    bot_rerun: bool
    branch: str
    migrator_name: str
    migrator_version: int
    name: str
    migrator_object_version: int
    pin_version: str
    static_libs: str
    # Used by version migrators
    version: str


class PackageTypedDict(TypedDict):
    name: str
    version: str


class RequirementsTypedDict(TypedDict, total=False):
    build: set[str]
    host: set[str]
    run: set[str]
    test: set[str]


class SourceTypedDict(TypedDict, total=False):
    fn: str
    patches: List[str]
    sha256: str
    url: str


class TestTypedDict(TypedDict, total=False):
    commands: List[str]
    imports: List[str]
    requires: List[str]
    requirements: List[str]


class PRedElementTypedDict(TypedDict, total=False):
    data: MigrationUidTypedDict
    PR: PR_TD


class CondaForgeYamlContents(TypedDict, total=False):
    bot: dict[str, typing.Any]
    provider: dict[str, str]


AttrsTypedDict = TypedDict(
    "AttrsTypedDict",
    {
        "about": AboutTypedDict,
        "build": BuildTypedDict,
        "branch": str,
        "conda-forge.yml": CondaForgeYamlContents,
        "extra": ExtraTypedDict,
        "feedstock_name": str,
        "meta_yaml": RecipeTypedDict,
        "package": PackageTypedDict,
        "raw_meta_yaml": str,
        "req": set[str],
        "name": str,
        "platforms": List[str],
        "pr_info": typing.Any,
        "requirements": RequirementsTypedDict,
        "source": SourceTypedDict,
        "test": TestTypedDict,
        "version": str,
        "new_version": str | bool,
        "archived": bool,
        "outputs_names": set[str],
        "PRed": list[PRedElementTypedDict],
        "version_pr_info": typing.Any,
        "url": str,
        "parsing_error": str | Literal[False],
        # Legacy types in here
        "bad": Union[bool, str],
    },
    total=False,
)
