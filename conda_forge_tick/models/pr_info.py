from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BeforeValidator, TypeAdapter, field_validator, model_validator

from conda_forge_tick.models.common import (
    CondaVersionString,
    NoneIsEmptyDict,
    PrJsonLazyJsonReference,
    StrictBaseModel,
)
from conda_forge_tick.models.pr_json import PullRequestDataValid, PullRequestInfoSpecial


def remove_azure_error(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("value is not a string.")
    if not value.startswith("No azure token. Create a token and\nput it"):
        raise ValueError("This is not an Azure token error.")
    return list(filter(None, value.split("\n")))[-1]


CondaVersionStringWithAzureTokenError = Annotated[
    CondaVersionString, BeforeValidator(remove_azure_error)
]
"""
Extracts a version from a string that contains an Azure token error.
"""


def one_plus_to_one(value: Any) -> int:
    if value != "1+":
        raise ValueError("This is not '1+'.")
    return 1


OnePlusToOne = Annotated[int, BeforeValidator(one_plus_to_one)]
"""
Receives a string "1+" and converts it into 1.
This is just for rolling back the effects of a typo in the aws_c_http0627 migration.
When this Pydantic model is used in production, serialize and deserialize the entire graph data to remove the error.
After that, this type can be removed.
"""


class MigratorName(StrEnum):
    """Each value here corresponds to a subclass of migrators.core.Migrator in the codebase."""

    VERSION = "Version"
    ARCH_REBUILD = "ArchRebuild"
    OSX_ARM = "OSXArm"
    WIN_ARM64 = "WinArm64"
    MIGRATION_YAML = "MigrationYaml"
    REBUILD = "Rebuild"
    BLAS_REBUILD = "BlasRebuild"
    R_BASE_REBUILD = "RBaseRebuild"
    G_FORTRAN_OSX_REBUILD = "GFortranOSXRebuild"
    REPLACEMENT = "Replacement"
    MATPLOTLIB_BASE = "MatplotlibBase"
    REBUILD_BROKEN = "RebuildBroken"
    MIGRATION_YAML_CREATOR = "MigrationYamlCreator"
    """
    Only operates on the conda-forge-pinning feedstock and updates the pinning version of packages.
    """
    NOARCH_PYTHON_MIN_MIGRATOR = "NoarchPythonMinMigrator"

    JS = "JS"
    """
    This legacy migrator for JavaScript technically exists in the codebase, but does not appear in the graph.
    """
    NOARCH = "Noarch"
    NOARCH_R = "NoarchR"
    """
    This legacy migrator R noarch packages technically exists in the codebase, but does not appear in the graph.
    """
    PINNING = "Pinning"
    COMPILER_REBUILD = "CompilerRebuild"
    """
    This migrator is no longer present in the codebase but still appears in the graph.
    """
    COMPILER = "Compiler"
    """
    This migrator is no longer present in the codebase but still appears in the graph.
    """
    OPEN_SSL_REBUILD = "OpenSSLRebuild"
    """
    This migrator is no longer present in the codebase but still appears in the graph.
    """

    ADD_NVIDIA_TOOLS = "AddNVIDIATools"


class MigrationPullRequestData(StrictBaseModel):
    """Sometimes, this object is called `migrator_uid` or `MigrationUidTypedDict` in the code."""

    bot_rerun: bool | datetime
    """
    If the migration was rerun because the bot-rerun label was added to the PR, this is set to the timestamp of the
    rerun. If no rerun was performed, this is False. There are some legacy PRs where is is True, indicating an absent
    timestamp of a rerun that was performed.
    """

    migrator_name: MigratorName
    """
    The name of the migrator that created the PR. As opposed to `pre_pr_migrator_status`, `pre_pr_migrator_attempt_ts`,
    and `pre_pr_migrator_attempts` below, the names of migrators appear here with spaces and not necessarily in
    lowercase.
    """

    migrator_version: int
    """
    The version of the migrator that created the PR.
    """

    version: CondaVersionString | None = None
    """
    If migrator_name is "Version", this fields contains the version that was migrated to.
    Otherwise, this field is None.
    """

    @model_validator(mode="after")
    def check_version(self) -> Self:
        if self.version is None and self.migrator_name == "Version":
            raise ValueError(
                "The version field must be set if migrator_name is 'Version'."
            )
        if self.version is not None and self.migrator_name != "Version":
            raise ValueError(
                "The version field must be None if migrator_name is not 'Version'."
            )
        return self

    migrator_object_version: int | OnePlusToOne | None = None
    """
    This field is taken from the migration YAML for YAML-based migrations. In the migration YAML, this field is called
    `migration_number`. Increasing the migrator object version is a way to force a migration to be rerun.
    The version of the migrator object (see above) is different from this value.
    https://github.com/conda-forge/conda-forge-pinning-feedstock/blob/0d70e56969f0fcba4e6211cd93224abbfe3c919f/recipe/migrations/example.exyaml#L9-L11
    Non-YAML migrators do not set this field.

    Refer to OnePlusToOne for more information about the 1+ case (legacy typo fix).
    """

    name: str | None = None
    """
    The name of the migration executed by the migrator. This is only used for YAML-based migrations and is the filename
    of the migration YAML file, without the .yaml or .yml extension. Otherwise, this field is missing.
    """

    branch: str | None = None
    """
    The branch that was migrated. Only set if not equal to "master" or "main", which seems a bit questionable.
    """

    # noinspection PyNestedDecorators
    @field_validator("branch")
    @classmethod
    def check_branch(cls, value: str) -> str:
        if value in ("master", "main"):
            raise ValueError("The branch field must not be 'master' or 'main'.")
        return value

    pin_version: str | None = None
    """
    This is only set by MigrationYamlCreator and specifies the version of the package that is pinned in the migration.
    """

    @model_validator(mode="after")
    def validate_pin_version(self) -> Self:
        if self.pin_version is None and (
            self.migrator_name == MigratorName.MIGRATION_YAML_CREATOR
        ):
            raise ValueError(
                "MigrationYamlCreator must have the pin_version field set."
            )

        if self.pin_version is not None and (
            self.migrator_name != MigratorName.MIGRATION_YAML_CREATOR
        ):
            raise ValueError(
                "Only MigrationYamlCreator can have the pin_version field set."
            )
        return self


class MigrationPullRequest(StrictBaseModel):
    PR: (
        PullRequestDataValid | PullRequestInfoSpecial | PrJsonLazyJsonReference | None
    ) = None
    """
    GitHub data about the pull request.
    This field may be missing.
    """

    data: MigrationPullRequestData


class ExceptionInfo(StrictBaseModel):
    """Information about an exception that occurred while performing migrations."""

    exception: str
    """
    The exception message.
    """

    traceback: list[str]
    """
    The traceback of the exception, split by newlines (may include empty strings).
    """

    code: int | None = None
    """
    If an HTTP error occurred, this field may contain the HTTP status code.
    """

    url: str | None = None
    """
    If an HTTP error occurred, this field may contain the URL that was requested.
    """


class PrInfoValid(StrictBaseModel):
    PRed: list[MigrationPullRequest] = []
    bad: str | ExceptionInfo | Literal[False] = False
    """
    If `False`, nothing bad happened. Otherwise, it indicates an error that occurred while performing migrations.
    Example: The feedstock was not found by the name defined in the graph or node attributes feedstock_name field.
    """

    pinning_version: str | None = None
    """
    The version of the conda-forge-pinning feedstock that was used for performing the LATEST migration of the feedstock.

    This can be None the feedstock has not been migrated yet, but it is also missing in other cases. There are NO
    assertions when this field is missing or present.
    """

    smithy_version: (
        CondaVersionString | CondaVersionStringWithAzureTokenError | None
    ) = None
    """
    The version of conda-smithy that was used for performing the LATEST migration of the feedstock.
    This can be None if the feedstock has not been migrated yet. There are NO assertions when this field is missing or
    present.

    A lot of feedstocks have an Azure token error in the smithy_version field, which is removed automatically.
    The Azure token errors should be removed from the graph, e.g. by parsing the model and re-serializing it.
    """

    pre_pr_migrator_status: NoneIsEmptyDict[str, str] = {}
    """
    A dictionary (migration name -> error message) of the error status of the migrations.
    Errors are added here if a non-version migration fails before a migration PR is created.
    This field can contain HTML tags, which are probably intended for the status page.

    The same thing for version migrations is part of the `version_pr_info` object.

    There are implicit assumptions about the contents of this field, but they are not documented.
    Refer to status_report.graph_migrator_status, for example.

    Note: The names of migrators appear here without spaces and in lowercase. This is not always the case.

    If a migration is eventually successful, the corresponding key is removed from the dictionary.
    """

    pre_pr_migrator_attempts: NoneIsEmptyDict[str, int] = {}
    """
    A dictionary (migration name -> number of attempts) of the number of attempts of the migrations.
    This value is increased by 1 every time a migration fails before a migration PR is created.

    Note: The names of migrators appear here without spaces and in lowercase. This is not always the case.

    If a migration is eventually successful, the corresponding key is removed from the dictionary.
    """

    pre_pr_migrator_attempt_ts: NoneIsEmptyDict[str, int] = {}
    """
    A dictionary (migration name -> timestamp) of the timestamp as `int(time.time())` of most recent
    attempt to make the migration PR.

    Note: The names of migrators appear here without spaces and in lowercase. This is not always the case.

    If a migration is eventually successful, the corresponding key is removed from the dictionary.
    """

    @model_validator(mode="after")
    def check_pre_pr_migrations(self) -> Self:
        if self.pre_pr_migrator_status.keys() != self.pre_pr_migrator_attempts.keys():
            raise ValueError(
                "The keys (migration names) of pre_pr_migrator_status and pre_pr_migrator_attempts must match."
            )
        if self.pre_pr_migrator_status.keys() != self.pre_pr_migrator_attempt_ts.keys():
            raise ValueError(
                "The keys (migration names) of pre_pr_migrator_status and pre_pr_migrator_attempt_ts must match."
            )
        return self


PrInfo = TypeAdapter(PrInfoValid)
