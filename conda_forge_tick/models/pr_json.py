from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import UUID4, AnyHttpUrl, Field, TypeAdapter
from pydantic_extra_types.color import Color

from conda_forge_tick.models.common import RFC2822Date, StrictBaseModel


class PullRequestLabelShort(StrictBaseModel):
    name: str
    """
    The name of the label.
    """


class PullRequestLabel(PullRequestLabelShort):
    color: Color
    """
    The color of the label, parsed as a hex color.
    """
    default: bool
    """
    Whether this is a GitHub default label (e.g. bug, documentation, enhancement).
    """
    description: str | None = None
    id: int
    """
    The GitHub label ID.
    """
    node_id: str
    """
    The GitHub-internally used node ID of the label.
    """
    url: AnyHttpUrl
    """
    A URL pointing to the GitHub label API endpoint:
    https://docs.github.com/de/rest/issues/labels?apiVersion=2022-11-28#get-a-label
    """


class PullRequestState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    """
    Merged PRs are also closed.
    """


class PullRequestInfoHead(StrictBaseModel):
    ref: str
    """
    The head branch of the pull request.
    This is set to "<this_is_not_a_branch>" or "this_is_not_a_branch" (without the angle brackets) if the branch is
    deleted, which seems unnecessary.
    """


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


class PullRequestDataValid(StrictBaseModel):
    """
    Information about a pull request, as retrieved from the GitHub API.
    Refer to git_utils.PR_KEYS_TO_KEEP for the keys that are kept in the PR object.

    GitHub documentation: https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28#get-a-pull-request
    """

    e_tag: str | None = Field(None, alias="ETag")
    """
    HTTP ETag header field, allowing us to quickly check if the PR has changed.
    """

    last_modified: RFC2822Date | None = Field(None, alias="Last-Modified")
    """
    Taken from the GitHub response header.
    """
    # TODO: add a serializer for this field

    id: int | None = None
    """
    The GitHub Pull Request ID (not: the PR number).
    """

    html_url: AnyHttpUrl | None = None
    """
    The URL of the pull request on GitHub.
    """

    created_at: datetime | None = None
    updated_at: datetime | None = None
    merged_at: datetime | None = None
    """
    Note that this field is abused in PullRequestInfoSpecial.
    """
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
    labels: list[PullRequestLabel | PullRequestLabelShort] = []
    """
    All GitHub labels of the pull request.
    """
    head: PullRequestInfoHead | None = None
    base: GithubPullRequestBase | None = None


class PullRequestInfoSpecial(StrictBaseModel):
    """
    Used instead of pr_json.PullRequestInfo in the graph data to fake a closed pull request.
    This is probably not necessary and should be removed.
    """

    id: UUID4
    merged_at: Literal["never issued", "fix aarch missing prs"]
    state: Literal[PullRequestState.CLOSED]


PullRequestData = TypeAdapter(PullRequestDataValid | PullRequestInfoSpecial)
