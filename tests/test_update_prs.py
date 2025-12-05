"""Tests for update_prs module."""

import pytest
import networkx as nx

from conda_forge_tick.update_prs import _filter_feedstock_nodes, _update_pr



@pytest.mark.parametrize(
    "node_ids,feedstock_filter,expected",
    [
        (
            ["numpy-feedstock", "scipy-feedstock", "pandas-feedstock"],
            None,
            ["numpy-feedstock", "scipy-feedstock", "pandas-feedstock"],
        ),
        (
            ["numpy-feedstock", "scipy-feedstock"],
            "",
            ["numpy-feedstock", "scipy-feedstock"],
        ),
        (
            ["numpy-feedstock", "scipy-feedstock", "pandas-feedstock"],
            "numpy-feedstock",
            ["numpy-feedstock"],
        ),
        (
            ["numpy-feedstock", "scipy-feedstock", "pandas-feedstock"],
            "nonexistent-feedstock",
            [],
        ),
        ([], "numpy-feedstock", []),
        (
            ["NumPy-feedstock", "numpy-feedstock"],
            "numpy-feedstock",
            ["numpy-feedstock"],
        ),
    ],
)
def test_filter_feedstock_nodes(node_ids, feedstock_filter, expected):
    """Test filtering with various inputs."""
    result = _filter_feedstock_nodes(node_ids, feedstock_filter)
    assert result == expected


def test_returns_zero_when_feedstock_not_found():
    """Test that _update_pr returns (0, 0) when feedstock is not in graph."""
    gx = nx.DiGraph()
    gx.add_node("numpy-feedstock", payload={"pr_info": {"PRed": []}})
    gx.add_node("scipy-feedstock", payload={"pr_info": {"PRed": []}})

    def mock_update_function(*args, **kwargs):
        raise AssertionError(
            "Update function should not be called when feedstock not found"
        )

    succeeded, failed = _update_pr(
        mock_update_function,
        dry_run=True,
        gx=gx,
        job=1,
        n_jobs=1,
        feedstock_filter="nonexistent-feedstock",
        offline=True,
    )

    assert succeeded == 0
    assert failed == 0
