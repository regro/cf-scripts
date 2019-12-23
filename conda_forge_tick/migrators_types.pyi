from mypy_extensions import TypedDict, _TypedDictMeta
import typing
from typing import (
    Any,
    Dict,
    List,
    Set,
    Tuple,
    Union,
    Optional)


PackageName = typing.NewType('PackageName', str)


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

class PRHead_TD(TypedDict, tota=False):
    ref: str


class PR_TD(TypedDict, total=False):
    state: PRState
    head: PRHead_TD


class PEedElementTypedDict(TypedDict, total=False):
    data: MigrationUidTypedDict
    PR: PR_TD


class BlasRebuildMigrateTypedDict(TypedDict):
    bot_rerun: bool
    migrator_name: str
    migrator_version: int
    name: str


class BuildTypedDict(TypedDict, total=False):
    noarch: str
    number: str
    script: str


ExtraTypedDict = TypedDict(
    'ExtraTypedDict',
    {'recipe-maintainers': List[str]})


# class HTypedDict(TypedDict):
#     data: 'DataTypedDict'
#     keys: List[str]


MetaYamlOutputs = Any


class MetaYamlTypedDict(TypedDict, total=False):
    about: 'AboutTypedDict'
    build: 'BuildTypedDict'
    extra: 'ExtraTypedDict'
    package: 'PackageTypedDict'
    requirements: 'RequirementsTypedDict'
    source: 'SourceTypedDict'
    test: 'TestTypedDict'
    outputs: MetaYamlOutputs


class MigrationUidTypedDict(TypedDict, total=False):
    bot_rerun: bool
    migrator_name: str
    migrator_version: int
    name: str
    migrator_object_version: int
    # Used by version migrators
    version: str


class PackageTypedDict(TypedDict):
    name: str
    version: str


class RequirementsTypedDict(TypedDict, total=False):
    build: List[str]
    host: List[str]
    run: List[str]


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


class AttrsTypedDict_(TypedDict, total=False):
    about: AboutTypedDict
    build: BuildTypedDict
    extra: ExtraTypedDict
    feedstock_name: str
    meta_yaml: MetaYamlTypedDict
    package: PackageTypedDict
    raw_meta_yaml: str
    req: Set[str]
    requirements: RequirementsTypedDict
    source: SourceTypedDict
    test: TestTypedDict
    version: str
    new_version: Union[str, bool]
    archived: bool
    PRed: List[PEedElementTypedDict]
    # Legacy types in here
    bad: Union[bool, str]
    # TODO: ADD in
    #  "conda-forge.yml":

class CondaForgeYamlContents(TypedDict, total=False):
    provider: Dict[str, str]


CondaForgeYaml = TypedDict('CondaForgeYaml', {"conda-forge.yml": CondaForgeYamlContents})


class AttrsTypedDict(AttrsTypedDict_, CondaForgeYaml):
    pass