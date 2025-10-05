from typing import Literal, Self

from pydantic import AnyHttpUrl, AnyUrl, Field, model_validator

from conda_forge_tick.models.common import (
    EmptyStringIsNone,
    GitUrl,
    NoneIsEmptyList,
    SingleElementToList,
    SplitStringNewlineBefore,
    StrictBaseModel,
    ValidatedBaseModel,
)

"""
Refer to https://docs.conda.io/projects/conda-build/en/stable/resources/define-metadata.html for
a documentation of the fields.
"""


class Package(ValidatedBaseModel):
    name: str
    version: str | None = None
    """
    The version field can be missing if the `meta.yaml` outputs specify their own versions or if post-build versioning
    is used.
    https://docs.conda.io/projects/conda-build/en/stable/resources/define-metadata.html#package-version
    """


class BaseSource(ValidatedBaseModel):
    patches: NoneIsEmptyList[str] | SingleElementToList[str] = []
    folder: str | None = None


class UrlSource(BaseSource):
    url: list[AnyUrl] | SingleElementToList[AnyUrl]
    md5: str | None = Field(None, pattern=r"^[a-f0-9]{32}$")
    sha1: str | None = Field(None, pattern=r"^[a-f0-9]{40}$")
    sha256: str | None = Field(None, pattern=r"^[a-f0-9]{64}$")
    filename: str | None = Field(None, alias="fn")


class GitSource(BaseSource):
    git_url: AnyUrl
    git_rev: str = "HEAD"
    git_depth: int = -1
    """
    default: no shallow clone
    """


class MercurialSource(BaseSource):
    hg_url: AnyUrl
    hg_tag: str


class SvnSource(BaseSource):
    svn_url: AnyUrl
    svn_rev: str = "head"
    svn_ignore_externals: bool = False
    svn_username: str | None = None
    svn_password: str | None = None

    @model_validator(mode="after")
    def svn_username_and_password(self) -> Self:
        if self.svn_username is not None and self.svn_password is None:
            raise ValueError("svn_password must be set if svn_username is set")
        if self.svn_username is None and self.svn_password is not None:
            raise ValueError("svn_username must be set if svn_password is set")
        return self


class LocalPathSource(BaseSource):
    path: str


class PatchesOnlySource(BaseSource, StrictBaseModel):
    """Happens due to selectors and rendering of the `source` field."""

    pass


class FilenameOnlySource(BaseSource, StrictBaseModel):
    """Happens due to selectors and rendering of the `source` field."""

    filename: str | None = Field(None, alias="fn")


Source = (
    UrlSource
    | GitSource
    | MercurialSource
    | SvnSource
    | LocalPathSource
    | PatchesOnlySource
    | FilenameOnlySource
)


class BuildRunExportsExplicit(ValidatedBaseModel):
    weak: NoneIsEmptyList[str] | SingleElementToList[str] = []
    strong: NoneIsEmptyList[str] | SingleElementToList[str] = []


class Build(ValidatedBaseModel):
    number: int
    noarch: Literal["generic", "python"] | None = None
    """
    Note that there is a legacy syntax for `noarch: python` which is `noarch_python: True`
    There are 2 legacy feedstocks that use `noarch: true` (which is undocumented).
    This is not supported by this data model but should be treated as `noarch: generic`.
    """
    noarch_python: Literal[True] | None = None
    """
    Legacy Syntax for `noarch: python`
    """
    script: NoneIsEmptyList[str] | SingleElementToList[str] = []
    run_exports: (
        NoneIsEmptyList[str] | SingleElementToList[str] | BuildRunExportsExplicit
    ) = []


class Requirements(ValidatedBaseModel):
    build: NoneIsEmptyList[str] = []
    host: NoneIsEmptyList[str] = []
    run: NoneIsEmptyList[str] = []
    run_constrained: NoneIsEmptyList[str] = []


class Test(ValidatedBaseModel):
    commands: NoneIsEmptyList[str] | SplitStringNewlineBefore = []
    """
    Some feedstocks (03/2024: ~80) use a string instead of a list for the `test/commands` field.
    Multiple commands are separated by newlines.
    This is undocumented and should not be supported. Probably the bot behaves incorrectly today.
    """
    imports: NoneIsEmptyList[str] | SingleElementToList[str] = []
    requires: NoneIsEmptyList[str] = []


class Output(ValidatedBaseModel):
    name: str
    version: str | None = None


class About(ValidatedBaseModel):
    description: str | None = None
    dev_url: AnyHttpUrl | GitUrl | EmptyStringIsNone | None = None
    doc_url: AnyHttpUrl | EmptyStringIsNone | None = None
    """Note! Both dev_url and doc_url are supposed to URLs. However, currently
    conda-forge's tooling does not enforce this constraint.
    """
    home: str | EmptyStringIsNone | None = None
    """
    Note! According to the conda documentation, this should be a single (!) URL.

    However, a lot of feedstocks do not conform to this rule. They use a list of URLs
    (separated by whitespace or commas). Example: `https://github.com/a/b, https://github.com/a/c`

    Some do even even add comments like this or similar: `https://a.com (homepage) https://b.com (documentation)`

    This field is currently blindly used for making hyperlinks, assuming it is a single URL.

    A fix would be to migrate feedstocks to use a single URL. Around 150 feedstocks are affected.
    """
    license: str | None = None
    license_family: str | None = None
    license_file: str | NoneIsEmptyList[str] = []
    summary: str | None = None


class Extra(ValidatedBaseModel):
    recipe_maintainers: NoneIsEmptyList[str] = Field(..., alias="recipe-maintainers")


class MetaYaml(ValidatedBaseModel):
    package: Package
    source: Source | list[Source] = []
    build: Build
    requirements: Requirements | None = None
    test: Test | None = None
    outputs: list[Output] = []
    about: About
    extra: Extra | None = None
