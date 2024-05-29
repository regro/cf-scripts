from conda_forge_tick.contexts import DEFAULT_BRANCHES, FeedstockContext
from conda_forge_tick.migrators_types import AttrsTypedDict

# to make the typechecker happy, this satisfies the AttrsTypedDict type
demo_attrs = AttrsTypedDict(
    {"conda-forge.yml": {"provider": {"default_branch": "main"}}}
)


def test_feedstock_context_default_branch():
    context = FeedstockContext("TEST-FEEDSTOCK-NAME", demo_attrs)
    assert context.default_branch == "main"

    DEFAULT_BRANCHES["TEST-FEEDSTOCK-NAME"] = "develop"
    assert context.default_branch == "develop"

    context.default_branch = "feature"
    assert context.default_branch == "feature"

    # reset the default branches
    DEFAULT_BRANCHES.pop("TEST-FEEDSTOCK-NAME")

    # test the default branch is still the same
    assert context.default_branch == "feature"


def test_feedstock_context_git_repo_owner():
    context = FeedstockContext("TEST-FEEDSTOCK-NAME", demo_attrs)
    assert context.git_repo_owner == "conda-forge"


def test_feedstock_context_git_repo_name():
    context = FeedstockContext("TEST-FEEDSTOCK-NAME", demo_attrs)
    assert context.git_repo_name == "TEST-FEEDSTOCK-NAME-feedstock"


def test_feedstock_context_git_href():
    context = FeedstockContext("TEST-FEEDSTOCK-NAME", demo_attrs)
    assert (
        context.git_href
        == "https://github.com/conda-forge/TEST-FEEDSTOCK-NAME-feedstock"
    )
