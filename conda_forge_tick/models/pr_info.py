from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    UUID4,
    AnyHttpUrl,
    BeforeValidator,
    Field,
    TypeAdapter,
    model_validator,
)

from conda_forge_tick.models.common import (
    PrJsonLazyJsonReference,
    StrictBaseModel,
    ValidatedBaseModel,
    VersionString,
    before_validator_ensure_dict,
)


def remove_azure_error(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("value is not a string.")
    if not value.startswith("No azure token. Create a token and\nput it"):
        raise ValueError("This is not an Azure token error.")
    return list(filter(None, value.split("\n")))[-1]


VersionStringWithAzureTokenError = Annotated[
    VersionString, BeforeValidator(remove_azure_error)
]
"""
Extracts a version from a string that contains an Azure token error.
"""


class PullRequestState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    """
    Merged PRs are also closed.
    """


class PullRequestLabel(StrictBaseModel):
    name: str
    """
    The name of the label.
    """


class PullRequestInfoHead(StrictBaseModel):
    ref: Literal["<this_is_not_a_branch>"]


class GithubPullRequestMergeableState(StrEnum):
    """
    These values are not officially documented by GitHub.
    See https://github.com/octokit/octokit.net/issues/1763#issue-297399985 for more information
    and an explanation of the different possible values.
    """

    DIRTY = "dirty"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"
    BEHIND = "behind"
    UNSTABLE = "unstable"
    HAS_HOOKS = "has_hooks"
    CLEAN = "clean"


class GithubRepository(StrictBaseModel):
    name: str


class GithubPullRequestBase(StrictBaseModel):
    repo: GithubRepository


class PullRequestInfo(StrictBaseModel):
    """
    Information about a pull request, as retrieved from the GitHub API.
    Refer to git_utils.PR_KEYS_TO_KEEP for the keys that are kept in the PR object.
    """

    # TODO: add docstrings

    e_tag: str | None = Field(None, alias="ETag")
    last_modified: datetime | None = Field(None, alias="Last-Modified")
    id: int | UUID4 | None = None
    html_url: AnyHttpUrl | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    merged_at: datetime | None = None
    closed_at: datetime | None = None
    mergeable_state: GithubPullRequestMergeableState | None = None
    """
    Undocumented GitHub API field. See here: https://github.com/octokit/octokit.net/issues/1763#issue-297399985
    """
    mergeable: bool | None = None
    merged: bool | None = None
    draft: bool | None = None

    number: int | None = None
    """
    The pull request number. Sometimes, this information is missing.
    """
    state: PullRequestState
    """
    Whether the pull request is open or closed.
    """
    labels: list[PullRequestLabel] = []
    """
    All GitHub labels of the pull request.
    """
    head: PullRequestInfoHead | None = None
    base: GithubPullRequestBase | None = None


class PullRequestInfoSpecial(StrictBaseModel):
    id: UUID4
    merged_at: Literal["never issued", "fix aarch missing prs"]
    state: Literal[PullRequestState.CLOSED]


class MigrationPullRequestData(StrictBaseModel):
    """
    Sometimes, this object is called `migrator_uid` or `MigrationUidTypedDict` in the code.
    """

    bot_rerun: bool | datetime
    """
    If the migration was rerun because the bot-rerun label was added to the PR, this is set to the timestamp of the
    rerun. If no rerun was performed, this is False. There are some legacy PRs where is is True, indicating an absent
    timestamp of a rerun that was performed.
    """

    migrator_name: str
    """
    The name of the migrator that created the PR. As opposed to `pre_pr_migrator_status` and `pre_pr_migrator_attempts`
    below, the names of migrators appear here with spaces and not necessarily in lowercase.
    """

    migrator_version: int
    """
    The version of the migrator that created the PR.
    """

    version: str | None = None
    """
    If migrator_name is "Version", this fields contains the version that was migrated to.
    Otherwise, this field is None.
    The version is not always a VersionString: For example, it can be 1.0-6

    This is a legacy field since version migration information is now stored in the `version_pr_info` object.
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

    migrator_object_version: int | None = None
    """
    This field is taken from the migration YAML for YAML-based migrations. In the migration YAML, this field is called
    `migration_number`. Increasing the migrator object version is a way to force a migration to be rerun.
    The version of the migrator object (see above) is different from this value.
    https://github.com/conda-forge/conda-forge-pinning-feedstock/blob/0d70e56969f0fcba4e6211cd93224abbfe3c919f/recipe/migrations/example.exyaml#L9-L11
    Non-YAML migrators do not set this field.
    """

    name: str | None = None
    """
    The name of the migration executed by the migrator. This is only used for YAML-based migrations and is the filename
    of the migration YAML file, without the .yaml or .yml extension. Otherwise, this field is missing.
    """

    branch: str | None = None
    pin_version: str | None = (
        None  # TODO: only conda-forge-pinning MigrationYamlCreator
    )


class MigrationPullRequest(StrictBaseModel):
    PR: PullRequestInfoSpecial | PullRequestInfo | PrJsonLazyJsonReference | None = None
    """
    GitHub data about the pull request.
    This field may be missing.
    """

    data: MigrationPullRequestData

    # noinspection PyNestedDecorators
    @model_validator(mode="before")
    @classmethod
    def validate_keys(cls, input_data: Any) -> Any:
        """
        The current implementation uses a field "keys" which is a list of all keys present in the
        MigrationPullRequestData object, duplicating them. This list is redundant and should be removed.
        The consistency of this field is validated here, after which it is removed.
        """
        input_data = before_validator_ensure_dict(input_data)

        if "keys" not in input_data:
            raise ValueError("The keys field is missing.")
        if "data" not in input_data:
            raise ValueError("The data field is missing.")

        keys = input_data.pop("keys")
        if not isinstance(keys, list):
            raise ValueError("The keys field must be a list.")

        data = input_data["data"]
        if not isinstance(data, dict):
            raise ValueError("The data field must be a dictionary.")

        if set(keys) != set(data.keys()):
            raise ValueError(
                "The keys field must exactly contain all keys of the data field."
            )

        return input_data


class PrInfoValid(StrictBaseModel):
    PRed: list[MigrationPullRequest] = []  # TODO: note about closed PRs
    bad: Literal[False] = False
    """
    See `PrInfoError` for the (bad is not False) case.
    """

    pinning_version: str | None = None
    """
    The version of the conda-forge-pinning feedstock that was used for performing the LATEST migration of the feedstock.

    This can be None the feedstock has not been migrated yet, but it is also missing in other cases. There are NO
    assertions when this field is missing or present.
    """

    smithy_version: VersionStringWithAzureTokenError | VersionString | None = None
    """
    The version of conda-smithy that was used for performing the LATEST migration of the feedstock.
    This can be None if the feedstock has not been migrated yet. There are NO assertions when this field is missing or
    present.

    A lot of feedstocks have an Azure token error in the smithy_version field, which is removed automatically.
    The Azure token errors should be removed from the graph, e.g. by parsing the model and re-serializing it.
    """

    pre_pr_migrator_status: dict[str, str]
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

    pre_pr_migrator_attempts: dict[str, int]
    """
    A dictionary (migration name -> number of attempts) of the number of attempts of the migrations.
    This value is increased by 1 every time a migration fails before a migration PR is created.

    Note: The names of migrators appear here without spaces and in lowercase. This is not always the case.

    If a migration is eventually successful, the corresponding key is removed from the dictionary.
    """

    @model_validator(mode="after")
    def check_pre_pr_migrations(self) -> Self:
        if self.pre_pr_migrator_status.keys() != self.pre_pr_migrator_attempts.keys():
            raise ValueError(
                "The keys (migration names) of pre_pr_migrator_status and pre_pr_migrator_attempts must match."
            )
        return self


class ExceptionInfo(StrictBaseModel):
    """
    Information about an exception that occurred while performing migrations.
    """

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


class PrInfoError(ValidatedBaseModel):
    bad: str | ExceptionInfo
    """
    Indicates an error that occurred while performing migrations.
    Example: The feedstock was not found by the name defined in the graph or node attributes feedstock_name field.
    """


PrInfo = TypeAdapter(PrInfoValid | PrInfoError)
