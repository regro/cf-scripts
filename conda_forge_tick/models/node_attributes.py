from collections import defaultdict
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, TypeAdapter, field_validator, model_validator

from conda_forge_tick.models.conda_forge_yml import BuildPlatform, CondaForgeYml
from conda_forge_tick.models.meta_yaml import MetaYaml
from conda_forge_tick.models.set import Set


class BuildSpecificRequirements(BaseModel):
    """
    A platform-specific list of requirements taken from the `recipe/meta.yaml` file in the feedstock repository.
    The build, host, run, and run_constrained sections are identical to the corresponding sections in the `meta.yaml`
    file, whereas the test requirements section is taken from the test section in the `meta.yaml` file.
    Refer to https://docs.conda.io/projects/conda-build/en/stable/resources/define-metadata.html#requirements-section
    for a documentation of the fields in the meta.yaml file.
    """

    build: Set[str] | None = None
    host: Set[str] | None = None
    run: Set[str] | None = None
    run_constrained: Set[str] | None = None
    test: Set[str] | None = None

    class Config:
        extra = "forbid"


class BuildPlatformInfo(BaseModel):
    meta_yaml: MetaYaml
    """
    A platform-specific representation of the `recipe/meta.yaml` file in the feedstock repository.
    """
    requirements: BuildSpecificRequirements
    """
    The platform-specific list of requirements taken from the `recipe/meta.yaml` file in the feedstock repository.
    """


class NodeAttributesValid(BaseModel):
    archived: bool
    """
    Is the feedstock repository archived?
    Archived feedstocks are excluded from most bot operations and never receive updates.

    Some very old feedstocks (~ 20) do not have this attribute.
    """

    branch: str
    """
    The branch of the feedstock repository to track. This is usually the default branch of the feedstock repository.
    For new feedstocks, this defaults to `main`.
    """

    conda_forge_yml: CondaForgeYml = Field(..., alias="conda-forge.yml")
    """
    A parsed representation of the `conda-forge.yml` file in the feedstock repository.
    """

    raw_meta_yaml: str
    """
    The raw content of the `recipe/meta.yaml` file in the feedstock repository.
    """

    feedstock_name: str
    """
    The name of the feedstock. If the GitHub feedstock repository has the name `foo-feedstock`,
    then the feedstock name is `foo`. Also, the node attributes JSON file is named `foo.json`.
    """

    hash_type: str | None = Field(None, examples=["sha256", "sha512", "md5"])
    """
    The type of hash used to verify the integrity of source archives. This is extracted from the source section of the
    `recipe/meta.yaml` file in the feedstock repository, as documented here:
    https://docs.conda.io/projects/conda-build/en/stable/resources/define-metadata.html#source-from-tarball-or-zip-archive
    The hash algorithm must be present in hashlib.algorithms_available.
    If multiple supported hash algorithms are present, the lexicographically largest one is chosen.
    If multiple sources are present, we consider the union (not: intersection) of all their hash types,
    which is probably not a good idea.

    If the sources section is missing, or all hash types are unsupported, this field is None (missing in the JSON).

    MD5 is obviously not recommended but used by a lot of feedstocks.
    """

    parsing_error: Literal[False]
    """
    Denotes an error that occurred while parsing the feedstock repository.
    If no error occurred, this is `False`.
    """

    platforms: set[BuildPlatform]
    """
    The list of build platforms (not: target platforms) this feedstock uses. For new feedstocks, this is inferred from
    the `*.yaml` files in the `.ci_support` directory of the feedstock repository. It consists of a platform name and
    an architecture name, separated by an underscore.

    If the .ci_support directory is missing or empty, this is set to `["win_64", "osx_64", "linux_64"]`, concatenated
    with the build platforms present in the `provider` section of the `conda-forge.yml` file. Duplicates are not
    removed (the current implementation uses a list), which is probably not a good idea (but the .ci_support directory
    should not be empty after all).
    """

    # noinspection PyNestedDecorators
    @model_validator(mode="before")
    @classmethod
    def move_platform_info(cls, data: Any) -> Any:
        """
        The current autotick-bot implementation makes use of `PLATFORM_meta_yaml` and `PLATFORM_requirements` fields
        that are present in this model, where PLATFORM is a build platform present in `platforms`.
        This data model is a bit too complex for what it does, so we transform it into a simpler model that is easier to
        work with. See platform_info below for the new model.
        """
        if not isinstance(data, dict):
            raise ValueError(
                "We only support validating dicts. Pydantic supports calling model_validate with some "
                "other objects (e.g. in conjunction with construct), but we do not. "
                "See https://docs.pydantic.dev/latest/concepts/validators/#model-validators"
            )

        if "platform_info" in data:
            raise ValueError(
                "The `platform_info` field is reserved for the new model and must not be present in the old model."
            )

        data["platform_info"] = defaultdict(dict)
        for build_platform in BuildPlatform:
            if f"{build_platform}_meta_yaml" in data:
                data["platform_info"][build_platform]["meta_yaml"] = data.pop(
                    f"{build_platform}_meta_yaml"
                )
            if f"{build_platform}_requirements" in data:
                data["platform_info"][build_platform]["requirements"] = data.pop(
                    f"{build_platform}_requirements"
                )

        return data

    @model_validator(mode="after")
    def check_all_platform_infos_present(self) -> Self:
        """
        Ensure that the `platform_info` field is present for all build platforms in the `platforms` field.
        """
        if set(self.platform_info.keys()) != self.platforms:
            raise ValueError(
                "The `platform_info` field must contain all build platforms in the `platforms` field."
            )
        return self

    platform_info: dict[BuildPlatform, BuildPlatformInfo]
    """TODO: complete"""
    # TODO: validate only platforms are present


class NodeAttributesError(BaseModel):
    parsing_error: str
    """
    Denotes an error that occurred while parsing the feedstock repository.
    """


NodeAttributes = TypeAdapter(NodeAttributesValid | NodeAttributesError)
