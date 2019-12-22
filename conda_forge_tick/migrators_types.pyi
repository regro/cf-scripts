from mypy_extensions import TypedDict
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


class PEedElementTypedDict(TypedDict):
    data: MigrationUidTypedDict


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


class AttrsTypedDict(TypedDict, total=False):
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
    archived: bool
    PRed: List[PEedElementTypedDict]
    # Legacy types in here
    bad: Union[bool, str]


# class BlasRebuild:
#     def migrate(
#         self,
#         recipe_dir: LocalPath,
#         attrs: 'AttrsTypedDict',
#         **kwargs
#     ) -> 'BlasRebuildMigrateTypedDict': ...
#
#
# class Compiler:
#     def filter(self, attrs, not_bad_str_start: str = ...) -> bool: ...
#     def migrate(
#         self,
#         recipe_dir: LocalPath,
#         attrs: 'AttrsTypedDict',
#         **kwargs
#     ) -> 'CompilerMigrateTypedDict': ...
#     def pr_body(self, feedstock_ctx: None) -> str: ...
#
#
# class JS:
#     def filter(self, attrs, not_bad_str_start: str = ...) -> bool: ...
#     def migrate(
#         self,
#         recipe_dir: LocalPath,
#         attrs[str, Union[Dict[str, str], Dict[str, List[str]], Dict[str, Union[Dict[str, str], Dict[str, List[str]]]], str, Set[str]]],
#         **kwargs
#     ) -> 'JSMigrateTypedDict': ...
#     def pr_body(self, feedstock_ctx: None) -> str: ...
#
#
# class LicenseMigrator:
#     def filter(self, attrs, not_bad_str_start: str = ...) -> bool: ...
#     def migrate(self, recipe_dir: LocalPath, attrs: 'AttrsTypedDict', **kwargs) -> None: ...
#
#
# class MigrationYaml:
#     def migrate(self, recipe_dir: str, attrs: 'AttrsTypedDict', **kwargs) -> 'MigrationYamlMigrateTypedDict': ...
#     def migrator_uid(self, attrs: 'AttrsTypedDict') -> 'MigrationYamlMigratorUidTypedDict': ...
#
#
# class Migrator:
#     def bind_to_ctx(self, migrator_ctx: MigratorContext) -> None: ...
#     def filter(self, attrs, not_bad_str_start: str = ...) -> bool: ...
#     def migrate(
#         self,
#         recipe_dir: Union[str, LocalPath],
#         attrs[str, Any],
#         **kwargs
#     ) -> Dict[str, Union[bool, str, int]]: ...
#     def migrator_uid(self, attrs) -> dict: ...
#     def new_build_number(self, old_number: int) -> int: ...
#     def pr_body(self, feedstock_ctx: FeedstockContext) -> str: ...
#     def set_build_number(self, filename: str) -> None: ...
#
#
# class Noarch:
#     def filter(self, attrs, not_bad_str_start: str = ...) -> bool: ...
#     def migrate(
#         self,
#         recipe_dir: LocalPath,
#         attrs: 'AttrsTypedDict',
#         **kwargs
#     ) -> 'NoarchMigrateTypedDict': ...
#     def pr_body(self, feedstock_ctx: None) -> str: ...
#
#
# class NoarchR:
#     def filter(self, attrs, not_bad_str_start: str = ...) -> bool: ...
#     def migrate(
#         self,
#         recipe_dir: LocalPath,
#         attrs[str, Any],
#         **kwargs
#     ) -> 'NoarchRMigrateTypedDict': ...
#     def pr_body(self, feedstock_ctx: None) -> str: ...
#
#
# class Pinning:
#     def filter(self, attrs, not_bad_str_start: str = ...) -> bool: ...
#     def migrate(
#         self,
#         recipe_dir: LocalPath,
#         attrs: 'AttrsTypedDict',
#         **kwargs
#     ) -> 'PinningMigrateTypedDict': ...
#     def pr_body(self, feedstock_ctx: None) -> str: ...
#
#
# class Rebuild:
#     def migrate(
#         self,
#         recipe_dir: LocalPath,
#         attrs[str, Any],
#         **kwargs
#     ) -> 'RebuildMigrateTypedDict': ...
#     def migrator_uid(self, attrs[str, Any]) -> 'RebuildMigratorUidTypedDict': ...
#
#
# class Replacement:
#     def filter(self, attrs[str, Any]) -> bool: ...
#     def migrate(
#         self,
#         recipe_dir: LocalPath,
#         attrs: 'AttrsTypedDict',
#         **kwargs
#     ) -> 'ReplacementMigrateTypedDict': ...
#     def pr_body(self, feedstock_ctx: None) -> str: ...
#
#
# class Version:
#     def _extract_version_from_hash(self, h: 'HTypedDict') -> str: ...
#     def filter(self, attrs, not_bad_str_start: str = ...) -> bool: ...
#     def find_urls(
#         self,
#         text: str
#     ) -> Union[List[Tuple[str, None, str]], List[Tuple[str, str, str]], List[Tuple[List[str], None, str]]]: ...
#     def get_hash_patterns(
#         self,
#         filename: str,
#         urls: Union[List[Tuple[str, None, str]], List[Tuple[str, str, str]], List[Tuple[List[str], None, str]]],
#         hash_type: str
#     ) -> Union[Tuple[Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str]], Tuple[Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str]], Tuple[Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str], Tuple[str, str, str]]]: ...
#     def migrate(
#         self,
#         recipe_dir: LocalPath,
#         attrs[str, Any],
#         hash_type: str = ...
#     ) -> 'VersionMigrateTypedDict': ...
#     def migrator_uid(self, attrs[str, Any]) -> 'VersionMigratorUidTypedDict': ...
#     @classmethod
#     def new_build_number(cls, old_build_number: int) -> int: ...
