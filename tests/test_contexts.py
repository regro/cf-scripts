import pytest

from conda_forge_tick.contexts import DEFAULT_BRANCHES, FeedstockContext
from conda_forge_tick.migrators_types import AttrsTypedDict

demo_attrs = {"conda-forge.yml": {"provider": {"default_branch": "main"}}}

demo_attrs_automerge = {
    "conda-forge.yml": {
        "provider": {"default_branch": "main"},
        "bot": {"automerge": True},
    }
}

demo_attrs_check_solvable = {
    "conda-forge.yml": {
        "provider": {"default_branch": "main"},
        "bot": {"check_solvable": True},
    }
}


def test_feedstock_context_default_branch_not_set():
    context = FeedstockContext("TEST-FEEDSTOCK-NAME", demo_attrs)
    assert context.default_branch == "main"

    # note: this does not overwrite the default branch
    DEFAULT_BRANCHES["TEST-FEEDSTOCK-NAME"] = "develop"
    assert context.default_branch == "main"

    DEFAULT_BRANCHES["TEST-FEEDSTOCK-NAME2"] = "develop"
    context2 = FeedstockContext("TEST-FEEDSTOCK-NAME2", demo_attrs)
    assert context2.default_branch == "develop"


def test_feedstock_context_default_branch_set():
    context = FeedstockContext("TEST-FEEDSTOCK-NAME", demo_attrs, "feature")

    DEFAULT_BRANCHES["TEST-FEEDSTOCK-NAME"] = "develop"
    assert context.default_branch == "feature"

    # reset the default branches
    DEFAULT_BRANCHES.pop("TEST-FEEDSTOCK-NAME")

    # test the default branch is still the same
    assert context.default_branch == "feature"


def test_feedstock_context_git_repo_owner():
    context = FeedstockContext("TEST-FEEDSTOCK-NAME", demo_attrs)
    assert context.git_repo_owner == "conda-forge"

    override_git_repo_owner_context = FeedstockContext(
        "TEST-FEEDSTOCK-NAME", demo_attrs, git_repo_owner="GIT_REPO_OWNER"
    )
    assert override_git_repo_owner_context.git_repo_owner == "GIT_REPO_OWNER"


def test_feedstock_context_git_repo_name():
    context = FeedstockContext("TEST-FEEDSTOCK-NAME", demo_attrs)
    assert context.git_repo_name == "TEST-FEEDSTOCK-NAME-feedstock"


def test_feedstock_context_git_http_ref():
    context = FeedstockContext("TEST-FEEDSTOCK-NAME", demo_attrs)
    assert (
        context.git_http_ref
        == "https://github.com/conda-forge/TEST-FEEDSTOCK-NAME-feedstock"
    )


@pytest.mark.parametrize("automerge", [True, False])
def test_feedstock_context_automerge(automerge: bool):
    context = FeedstockContext(
        "TEST-FEEDSTOCK-NAME", demo_attrs_automerge if automerge else demo_attrs
    )

    assert context.automerge == automerge


@pytest.mark.parametrize("check_solvable", [True, False])
def test_feedstock_context_check_solvable(check_solvable: bool):
    context = FeedstockContext(
        "TEST-FEEDSTOCK-NAME",
        demo_attrs_check_solvable if check_solvable else demo_attrs,
    )

    assert context.check_solvable == check_solvable


@pytest.mark.parametrize("default_branch", [None, "", "feature"])
@pytest.mark.parametrize(
    "attrs", [demo_attrs, demo_attrs_automerge, demo_attrs_check_solvable]
)
def test_feedstock_context_reserve_clone_directory(
    attrs: AttrsTypedDict, default_branch: str
):
    context = FeedstockContext("pytest", attrs, default_branch)

    with context.reserve_clone_directory() as cloned_context:
        assert cloned_context.feedstock_name == "pytest"
        assert cloned_context.attrs == attrs
        assert (
            cloned_context.default_branch == default_branch
            if default_branch
            else "main"
        )
        assert cloned_context.git_repo_owner == "conda-forge"
        assert cloned_context.git_repo_name == "pytest-feedstock"
        assert (
            cloned_context.git_http_ref
            == "https://github.com/conda-forge/pytest-feedstock"
        )

        assert cloned_context.local_clone_dir.exists()
        assert cloned_context.local_clone_dir.is_dir()
        assert cloned_context.local_clone_dir.name == "pytest-feedstock"

        with open(cloned_context.local_clone_dir / "test.txt", "w") as f:
            f.write("test")

        assert (cloned_context.local_clone_dir / "test.txt").exists()

    assert not cloned_context.local_clone_dir.exists()
