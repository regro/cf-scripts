# TODO: don't copy paste, but publish package
from __future__ import annotations

import json
from typing import Annotated, Any, Generic, Literal, TypeVar, Union

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    TypeAdapter,
    conint,
    constr,
)

NonEmptyStr = constr(min_length=1)
PathNoBackslash = constr(pattern=r"^[^\\]+$")
UnsignedInt = conint(ge=0)
GitUrl = constr(
    pattern=r"((git|ssh|http(s)?)|(git@[\w\.]+))(:(\/\/)?)([\w\.@:\/\\-~]+)"
)


class StrictBaseModel(BaseModel):
    class Config:
        extra = "forbid"


###########################
# Conditional formatting  #
###########################

T = TypeVar("T")
ConditionalList = Union[T, "IfStatement[T]", list[Union[T, "IfStatement[T]"]]]


class IfStatement(StrictBaseModel, Generic[T]):
    expr: str = Field(..., alias="if")
    then: T | list[T]
    otherwise: T | list[T] | None = Field(None, alias="else")


###################
# Glob section    #
###################

SingleGlob = NonEmptyStr

GlobVec = ConditionalList[SingleGlob]


class GlobDict(StrictBaseModel):
    include: GlobVec = Field(..., description="Glob patterns to include")
    exclude: GlobVec = Field([], description="Glob patterns to exclude")


Glob = SingleGlob | GlobVec | GlobDict

####################
# Package section  #
####################


class SimplePackage(StrictBaseModel):
    name: str = Field(description="The package name")
    version: str = Field(description="The package version")


class ComplexPackage(StrictBaseModel):
    name: str | None = Field(
        description="The recipe name, this is only used to identify the name of the recipe."
    )
    version: str | None = Field(
        None,
        description="The version of each output, this can be overwritten per output",
    )


###################
# Source section  #
###################

MD5Str = constr(min_length=32, max_length=32, pattern=r"[a-fA-F0-9]{32}")
SHA256Str = constr(min_length=64, max_length=64, pattern=r"[a-fA-F0-9]{64}")


class BaseSource(StrictBaseModel):
    patches: ConditionalList[PathNoBackslash] = Field(
        [], description="A list of patches to apply after fetching the source"
    )
    target_directory: NonEmptyStr | None = Field(
        None, description="The location in the working directory to place the source"
    )


class UrlSource(BaseSource):
    url: NonEmptyStr | list[NonEmptyStr] = Field(
        ...,
        description="Rrl pointing to the source tar.gz|zip|tar.bz2|... (this can be a list of mirrors that point to the same file)",
    )
    sha256: SHA256Str | None = Field(
        None, description="The SHA256 hash of the source archive"
    )
    md5: MD5Str | None = Field(None, description="The MD5 hash of the source archive")
    file_name: NonEmptyStr | None = Field(
        None,
        description="A file name to rename the downloaded file to (does not apply to archives).",
    )


class BaseGitSource(BaseSource):
    git: GitUrl | JinjaExpr = Field(
        ..., description="The url that points to the git repository."
    )
    depth: UnsignedInt | None = Field(
        None, description="A value to use when shallow cloning the repository."
    )
    lfs: bool = Field(
        default=False, description="Should we LFS files be checked out as well"
    )


class GitRev(BaseGitSource):
    rev: NonEmptyStr = Field(..., description="Revision to checkout to (hash or ref)")


class GitTag(BaseGitSource):
    tag: NonEmptyStr = Field(..., description="Tag to checkout")


class GitBranch(BaseGitSource):
    branch: NonEmptyStr = Field(..., description="Branch to check out")


GitSource = GitRev | GitTag | GitBranch | BaseGitSource


class LocalSource(BaseSource):
    path: str = Field(
        ..., description="A path on the local machine that contains the source."
    )
    sha256: SHA256Str | None = Field(
        None, description="The SHA256 hash of the source archive"
    )
    md5: MD5Str | None = Field(None, description="The MD5 hash of the source archive")
    use_gitignore: bool = Field(
        default=True,
        description="Whether or not to use the .gitignore file when copying the source.",
    )
    file_name: NonEmptyStr | None = Field(
        None,
        description="A file name to rename the file to (does not apply to archives).",
    )


Source = UrlSource | GitSource | LocalSource

###################
# Build section   #
###################

PythonEntryPoint = str
MatchSpec = str


class RunExports(StrictBaseModel):
    weak: ConditionalList[MatchSpec] | None = Field(
        None, description="Weak run exports apply from the host env to the run env"
    )
    strong: ConditionalList[MatchSpec] | None = Field(
        None,
        description="Strong run exports apply from the build and host env to the run env",
    )
    noarch: ConditionalList[MatchSpec] | None = Field(
        None,
        description="Noarch run exports are the only ones looked at when building noarch packages",
    )
    weak_constraints: ConditionalList[MatchSpec] | None = Field(
        None, description="Weak run constraints add run_constraints from the host env"
    )
    strong_constraints: ConditionalList[MatchSpec] | None = Field(
        None,
        description="Strong run constraints add run_constraints from the build and host env",
    )


class ScriptEnv(StrictBaseModel):
    passthrough: ConditionalList[NonEmptyStr] = Field(
        [],
        description="Environments variables to leak into the build environment from the host system. During build time these variables are recorded and stored in the package output. Use `secrets` for environment variables that should not be recorded.",
    )
    env: dict[str, str] = Field(
        {}, description="Environment variables to set in the build environment."
    )
    secrets: ConditionalList[NonEmptyStr] = Field(
        [],
        description="Environment variables to leak into the build environment from the host system that contain sensitve information. Use with care because this might make recipes no longer reproducible on other machines.",
    )


JinjaExpr = constr(pattern=r"\$\{\{.*\}\}")


class Build(StrictBaseModel):
    number: UnsignedInt | JinjaExpr | None = Field(
        0,
        description="Build number to version current build in addition to package version",
    )
    string: str | JinjaExpr | None = Field(
        None,
        description="The build string to identify build variant. This is usually omitted (can use `${{ hash }}`) variable here)",
    )
    skip: str | bool | list[str | bool] | None = Field(
        None,
        description="List of conditions under which to skip the build of the package. If any of these condition returns true the build is skipped.",
    )
    noarch: Literal["generic", "python"] | None = Field(
        None,
        description="Can be either 'generic' or 'python'. A noarch 'python' package compiles .pyc files upon installation.",
    )

    script: str | Script | ConditionalList[NonEmptyStr] | None = Field(
        None,
        description="The script to execute to invoke the build. If the string is a single line and ends with `.sh` or `.bat`, then we interpret it as a file.",
    )

    merge_build_and_host_envs: bool | JinjaExpr | None = Field(
        default=False,
        description="Merge the build and host environments (used in many R packages on Windows)",
    )

    always_include_files: ConditionalList[NonEmptyStr] = Field(
        [],
        description="Files to be included even if they are present in the PREFIX before building.",
    )
    always_copy_files: ConditionalList[Glob] = Field(
        [],
        description="Do not soft- or hard-link these files but instead always copy them into the environment",
    )
    variant: Variant | None = Field(
        None,
        description="Options that influence how the different variants are computed.",
    )
    python: Python | None = Field(
        None, description="Python specific build configuration"
    )
    dynamic_linking: DynamicLinking | None = Field(
        None,
        description="Configuration to post-process dynamically linked libraries and executables",
    )

    link_options: LinkOptions | None = Field(
        None,
        description="Options that influence how a package behaves when it is installed or uninstalled.",
    )

    prefix_detection: PrefixDetection | None = Field(
        None,
        description="Options that influence how the prefix replacement is done.",
    )

    files: Glob = Field(
        None, description="Glob patterns to include or exclude files from the package."
    )


class BaseScript(StrictBaseModel):
    interpreter: NonEmptyStr | None = Field(
        default=None,
        description="The interpreter to use for the script.\n\nDefaults to `bash` on unix and `cmd.exe` on Windows.",
    )
    env: dict[NonEmptyStr, str] = Field(
        default={},
        description='the script environment.\n\nYou can use Jinja to pass through environments variables with the `env` object (e.g. `${{ env.get("MYVAR") }}`)',
    )
    secrets: ConditionalList[NonEmptyStr] = Field(
        default=[],
        description="Secrets that are set as environment variables but never shown in the logs or the environment.",
    )


class FileScript(BaseScript):
    file: PathNoBackslash | JinjaExpr = Field(
        description="The file to use as the script. Automatically adds the `bat` or `sh` to the filename on Windows or Unix respectively (if no file extension is given)."
    )


class ContentScript(BaseScript):
    content: str | ConditionalList[str] = Field(
        description="A string or list of strings that is the scripts contents"
    )


Script = FileScript | ContentScript


class Variant(StrictBaseModel):
    use_keys: ConditionalList[NonEmptyStr] = Field(
        [],
        description="Keys to forcibly use for the variant computation (even if they are not in the dependencies)",
    )

    ignore_keys: ConditionalList[NonEmptyStr] = Field(
        [],
        description="Keys to forcibly ignore for the variant computation (even if they are in the dependencies)",
    )

    down_prioritize_variant: int | JinjaExpr = Field(
        0, description="used to prefer this variant less over other variants"
    )


class Python(StrictBaseModel):
    entry_points: ConditionalList[PythonEntryPoint] = Field(
        [],
    )

    use_python_app_entrypoint: bool | JinjaExpr = Field(
        default=False,
        description="Specifies if python.app should be used as the entrypoint on macOS. (macOS only)",
    )

    preserve_egg_dir: bool | JinjaExpr = Field(default=False)

    skip_pyc_compilation: ConditionalList[Glob] = Field(
        default=[], description="Skip compiling pyc for some files"
    )

    disable_pip: bool | JinjaExpr = Field(default=False)


class PrefixDetection(StrictBaseModel):
    force_file_type: ForceFileType | None = Field(
        None, description="force the file type of the given files to be TEXT or BINARY"
    )
    ignore: bool | JinjaExpr | ConditionalList[PathNoBackslash] = Field(
        default=False, description="Ignore all or specific files for prefix replacement"
    )
    ignore_binary_files: bool | JinjaExpr | ConditionalList[PathNoBackslash] = Field(
        default=False, description="Wether to detect binary files with prefix or not"
    )


class ForceFileType(StrictBaseModel):
    text: ConditionalList[Glob] = Field(default=[], description="force TEXT file type")
    binary: ConditionalList[Glob] = Field(
        default=[], description="force BINARY file type"
    )


class DynamicLinking(StrictBaseModel):
    rpaths: ConditionalList[NonEmptyStr] = Field(
        default=["lib/"], description="linux only, list of rpaths (was rpath)"
    )
    binary_relocation: bool | JinjaExpr | ConditionalList[Glob] = Field(
        default=True,
        description="Wether to relocate binaries or not. If this is a list of paths then only the listed paths are relocated",
    )
    missing_dso_allowlist: ConditionalList[Glob] = Field(
        default=[],
        description="Allow linking against libraries that are not in the run requirements",
    )
    rpath_allowlist: ConditionalList[Glob] = Field(
        default=[],
        description="Allow runpath/rpath to point to these locations outside of the environment",
    )
    overdepending_behavior: Literal["ignore", "error"] = Field(
        "error",
        description="What to do when detecting overdepending. Overdepending means that a requirement a run requirement is specified but none of the artifacts from the build link against any of the shared libraries of the requirement.",
    )
    overlinking_behavior: Literal["ignore", "error"] = Field(
        "error",
        description="What to do when detecting overdepending. Overlinking occurs when an artifact links against a library that was not specified in the run requirements.",
    )


class IgnoreRunExports(StrictBaseModel):
    by_name: ConditionalList[NonEmptyStr] = Field(
        default=[], description="ignore run exports by name (e.g. `libgcc-ng`)"
    )
    from_package: ConditionalList[NonEmptyStr] = Field(
        default=[],
        description="ignore run exports that come from the specified packages",
    )


class LinkOptions(StrictBaseModel):
    post_link_script: NonEmptyStr | None = Field(
        None,
        description="Script to execute after the package has been linked into an environment",
    )
    pre_unlink_script: NonEmptyStr | None = Field(
        None,
        description="Script to execute before uninstalling the package from an environment",
    )
    pre_link_message: NonEmptyStr | None = Field(
        None, description="Message to show before linking"
    )


#########################
# Requirements Section  #
#########################


class Requirements(StrictBaseModel):
    build: ConditionalList[MatchSpec] | None = Field(
        None,
        description="Dependencies to install on the build platform architecture. Compilers, CMake, everything that needs to execute at build time.",
    )
    host: ConditionalList[MatchSpec] | None = Field(
        None,
        description="Dependencies to install on the host platform architecture. All the packages that your build links against.",
    )
    run: ConditionalList[MatchSpec] | None = Field(
        None,
        description="Dependencies that should be installed alongside this package. Dependencies in the `host` section with `run_exports` are also automatically added here.",
    )
    run_constraints: ConditionalList[MatchSpec] | None = Field(
        None, description="constraints optional dependencies at runtime."
    )
    run_exports: ConditionalList[MatchSpec] | RunExports = Field(
        None, description="The run exports of this package"
    )
    ignore_run_exports: IgnoreRunExports | None = Field(
        None, description="Ignore run-exports by name or from certain packages"
    )


################
# Test Section #
################


class TestElementRequires(StrictBaseModel):
    build: ConditionalList[MatchSpec] | None = Field(
        None,
        description="extra requirements with build_platform architecture (emulators, ...)",
    )
    run: ConditionalList[MatchSpec] | None = Field(
        None, description="extra run dependencies"
    )


class TestElementFiles(StrictBaseModel):
    source: ConditionalList[NonEmptyStr] | None = Field(
        None, description="extra files from $SRC_DIR"
    )
    recipe: ConditionalList[NonEmptyStr] | None = Field(
        None, description="extra files from $RECIPE_DIR"
    )


class ScriptTestElement(StrictBaseModel):
    script: str | Script | ConditionalList[NonEmptyStr] = Field(
        None, description="A script to run to perform the test."
    )
    requirements: TestElementRequires | None = Field(
        None, description="Additional dependencies to install before running the test."
    )
    files: TestElementFiles | None = Field(
        None, description="Additional files to include for the test."
    )


class PythonTestElementInner(StrictBaseModel):
    imports: ConditionalList[NonEmptyStr] = Field(
        ...,
        description="A list of Python imports to check after having installed the built package.",
    )
    pip_check: bool = Field(
        default=True,
        description="Whether or not to run `pip check` during the Python tests.",
    )


class PythonTestElement(StrictBaseModel):
    python: PythonTestElementInner = Field(
        ..., description="Python specific test configuration"
    )


class DownstreamTestElement(StrictBaseModel):
    downstream: MatchSpec = Field(
        ...,
        description="Install the package and use the output of this package to test if the tests in the downstream package still succeed.",
    )


class PackageContentTestInner(StrictBaseModel):
    files: ConditionalList[NonEmptyStr] | None = Field(
        default=[], description="Files that should be in the package"
    )
    include: ConditionalList[NonEmptyStr] | None = Field(
        default=[],
        description="Files that should be in the `include/` folder of the package. This folder is found under `$PREFIX/include` on Unix and `$PREFIX/Library/include` on Windows.",
    )
    site_packages: ConditionalList[NonEmptyStr] | None = Field(
        default=[],
        description="Files that should be in the `site-packages/` folder of the package. This folder is found under `$PREFIX/lib/pythonX.Y/site-packages` on Unix and `$PREFIX/Lib/site-packages` on Windows.",
    )
    bin: ConditionalList[NonEmptyStr] | None = Field(
        default=[],
        description="Files that should be in the `bin/` folder of the package. This folder is found under `$PREFIX/bin` on Unix. On Windows this searches for files in `%PREFIX`, `%PREFIX%/bin`, `%PREFIX%/Scripts`, `%PREFIX%/Library/bin`, `%PREFIX/Library/usr/bin` and  `%PREFIX/Library/mingw-w64/bin`.",
    )
    lib: ConditionalList[NonEmptyStr] | None = Field(
        default=[],
        description="Files that should be in the `lib/` folder of the package. This folder is found under `$PREFIX/lib` on Unix and %PREFIX%/Library/lib on Windows.",
    )


class PackageContentTest(StrictBaseModel):
    package_contents: PackageContentTestInner = Field(
        ..., description="Test if the package contains the specified files."
    )


TestElement = (
    ScriptTestElement | PythonTestElement | DownstreamTestElement | PackageContentTest
)

#########
# About #
#########


class DescriptionFile(StrictBaseModel):
    file: PathNoBackslash = Field(
        ...,
        description="Path in the source directory that contains the packages description. E.g. README.md",
    )


class About(StrictBaseModel):
    # URLs
    homepage: AnyHttpUrl | None = Field(
        None, description="Url of the homepage of the package."
    )
    repository: AnyHttpUrl | None = Field(
        None,
        description="Url that points to where the source code is hosted e.g. (github.com)",
    )
    documentation: AnyHttpUrl | None = Field(
        None, description="Url that points to where the documentation is hosted."
    )

    # License
    license_: str | None = Field(
        None, alias="license", description="An license in SPDX format."
    )
    license_file: ConditionalList[PathNoBackslash] | None = Field(
        None, description="Paths to the license files of this package."
    )
    license_url: str | None = Field(
        None, description="A url that points to the license file."
    )

    # Text
    summary: str | None = Field(None, description="A short description of the package.")
    description: str | DescriptionFile | None = Field(
        None,
        description="Extented description of the package or a file (usually a README).",
    )

    prelink_message: str | None = None


###########
# Outputs #
###########


class OutputBuild(Build):
    cache_only: bool = Field(
        default=False,
        description="Do not output a package but use this output as an input to others.",
    )
    cache_from: ConditionalList[NonEmptyStr] | None = Field(
        None,
        description="Take the output of the specified outputs and copy them in the working directory.",
    )


class Output(StrictBaseModel):
    package: ComplexPackage | None = Field(
        None,
        description="The package name and version, this overwrites any top-level fields.",
    )

    source: ConditionalList[Source] | None = Field(
        None, description="The source items to be downloaded and used for the build."
    )
    build: OutputBuild | None = Field(
        None, description="Describes how the package should be build."
    )

    requirements: Requirements | None = Field(
        None, description="The package dependencies"
    )

    tests: (
        list[
            TestElement
            | IfStatement[TestElement]
            | list[TestElement | IfStatement[TestElement]]
        ]
        | None
    ) = Field(None, description="Tests to run after packaging")

    about: About | None = Field(
        None,
        description="A human readable description of the package information. The values here are merged with the top level `about` field.",
    )

    extra: dict[str, Any] | None = Field(
        None,
        description="An set of arbitrary values that are included in the package manifest. The values here are merged with the top level `extras` field.",
    )


#####################
# The Recipe itself #
#####################

SchemaVersion = Annotated[int, Field(ge=1, le=1)]


class BaseRecipe(StrictBaseModel):
    schema_version: SchemaVersion = Field(
        1,
        description="The version of the YAML schema for a recipe. If the version is omitted it is assumed to be 1.",
    )

    context: dict[str, Any] | None = Field(
        None, description="Defines arbitrary key-value pairs for Jinja interpolation"
    )

    source: None | Source | IfStatement[Source] | list[Source | IfStatement[Source]] = (
        Field(
            None,
            description="The source items to be downloaded and used for the build.",
        )
    )
    build: Build | None = Field(
        None, description="Describes how the package should be build."
    )

    about: About | None = Field(
        None, description="A human readable description of the package information"
    )
    extra: dict[str, Any] | None = Field(
        None,
        description="An set of arbitrary values that are included in the package manifest",
    )


class ComplexRecipe(BaseRecipe):
    recipe: ComplexPackage | None = Field(None, description="The package version.")

    outputs: ConditionalList[Output] = Field(
        ..., description="A list of outputs that are generated for this recipe."
    )


class SimpleRecipe(BaseRecipe):
    package: SimplePackage = Field(..., description="The package name and version.")

    tests: ConditionalList[TestElement] | None = Field(
        None, description="Tests to run after packaging"
    )

    requirements: Requirements | None = Field(
        None, description="The package dependencies"
    )


Recipe = TypeAdapter(SimpleRecipe | ComplexRecipe)


if __name__ == "__main__":
    print(json.dumps(Recipe.json_schema(), indent=2))
