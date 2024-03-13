from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BeforeValidator, TypeAdapter, model_validator

from conda_forge_tick.models.common import (
    StrictBaseModel,
    ValidatedBaseModel,
    VersionString,
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
    open = "open"
    closed = "closed"
    """
    Merged PRs are also closed.
    """


class PullRequestLabel(StrictBaseModel):
    name: str
    """
    The name of the label.
    """


class PullRequestInfo(StrictBaseModel):
    number: int
    """
    The pull request number.
    """
    state: PullRequestState
    """
    Whether the pull request is open or closed.
    """
    labels: list[PullRequestLabel]
    """
    All GitHub labels of the pull request.
    """


class MigrationPullRequestData(StrictBaseModel):
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


class MigrationPullRequest(StrictBaseModel):
    PR: PullRequestInfo
    data: MigrationPullRequestData


class PrInfoValid(StrictBaseModel):
    PRed: list[MigrationPullRequest] = []
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
