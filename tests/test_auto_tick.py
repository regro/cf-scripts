from unittest import mock
from unittest.mock import ANY, MagicMock

import pytest

from conda_forge_tick.auto_tick import run_with_tmpdir
from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext

demo_attrs = {"conda-forge.yml": {"provider": {"default_branch": "main"}}}


@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("base_branch", ["main", "master"])
@pytest.mark.parametrize("rerender", [True, False])
@mock.patch("conda_forge_tick.auto_tick.run")
def test_run_with_tmpdir(
    run_mock: MagicMock, rerender: bool, base_branch: str, dry_run: bool
):
    context = FeedstockContext(
        feedstock_name="TEST-FEEDSTOCK-NAME",
        attrs=demo_attrs,
    )

    migrator = MagicMock()

    kwargs = {
        "these": "are",
        "some": "kwargs",
    }

    run_with_tmpdir(
        context=context,
        migrator=migrator,
        rerender=rerender,
        base_branch=base_branch,
        dry_run=dry_run,
        **kwargs,
    )

    run_mock.assert_called_once_with(
        context=ANY,
        migrator=migrator,
        rerender=rerender,
        base_branch=base_branch,
        dry_run=dry_run,
        **kwargs,
    )

    _, call_kwargs = run_mock.call_args

    cloned_context: ClonedFeedstockContext = call_kwargs["context"]
    assert isinstance(cloned_context, ClonedFeedstockContext)

    assert cloned_context.feedstock_name == context.feedstock_name
    assert cloned_context.default_branch == context.default_branch
