"""Tests for conda_forge_tick.version_filters module."""

from conda_forge_tick.version_filters import filter_version, is_version_ignored


def test_no_filtering_config():
    """Test that versions are not ignored when no filtering is configured."""
    attrs = {"conda-forge.yml": {"bot": {"version_updates": {}}}}
    assert is_version_ignored(attrs, "1.2.3") is False
    assert is_version_ignored(attrs, "2.0.0") is False


def test_explicit_exclusions():
    """Test explicit version exclusions."""
    attrs = {
        "conda-forge.yml": {"bot": {"version_updates": {"exclude": ["1.2.3", "2.0.0"]}}}
    }
    assert is_version_ignored(attrs, "1.2.3") is True
    assert is_version_ignored(attrs, "2.0.0") is True
    assert is_version_ignored(attrs, "1.2.4") is False


def test_normalized_version_exclusions():
    """Test that version normalization works for exclusions."""
    attrs = {"conda-forge.yml": {"bot": {"version_updates": {"exclude": ["1.2.3"]}}}}
    # Test that dashes and underscores are normalized to dots
    assert is_version_ignored(attrs, "1-2-3") is True
    assert is_version_ignored(attrs, "1_2_3") is True
    assert is_version_ignored(attrs, "1.2.3") is True


def test_odd_even_filtering_disabled():
    """Test that odd/even filtering is disabled by default."""
    attrs = {"conda-forge.yml": {"bot": {"version_updates": {}}}}
    # These have odd minor versions but should not be filtered
    assert is_version_ignored(attrs, "1.1.0") is False
    assert is_version_ignored(attrs, "2.3.5") is False


def test_odd_even_filtering_enabled():
    """Test odd/even version filtering when enabled."""
    attrs = {
        "conda-forge.yml": {"bot": {"version_updates": {"even_odd_versions": True}}}
    }
    # Odd minor versions should be filtered out
    assert is_version_ignored(attrs, "1.1.0") is True
    assert is_version_ignored(attrs, "2.3.5") is True
    assert is_version_ignored(attrs, "0.1.2") is True

    # Even minor versions should not be filtered
    assert is_version_ignored(attrs, "1.0.0") is False
    assert is_version_ignored(attrs, "2.2.5") is False
    assert is_version_ignored(attrs, "0.4.2") is False


def test_odd_even_filtering_with_normalization():
    """Test odd/even filtering with version normalization."""
    attrs = {
        "conda-forge.yml": {"bot": {"version_updates": {"even_odd_versions": True}}}
    }
    # Test with dashes and underscores
    assert is_version_ignored(attrs, "1-1-0") is True
    assert is_version_ignored(attrs, "1_1_0") is True
    assert is_version_ignored(attrs, "2-2-0") is False


def test_odd_even_filtering_invalid_version():
    """Test that invalid versions don't cause errors in odd/even filtering."""
    attrs = {
        "conda-forge.yml": {"bot": {"version_updates": {"even_odd_versions": True}}}
    }
    # These should not cause errors and should not be filtered
    assert is_version_ignored(attrs, "invalid") is False
    assert is_version_ignored(attrs, "1") is False  # Only one part
    assert is_version_ignored(attrs, "1.a.0") is False  # Non-numeric minor


def test_combined_filtering():
    """Test that both exclusions and odd/even filtering work together."""
    attrs = {
        "conda-forge.yml": {
            "bot": {
                "version_updates": {"exclude": ["1.0.0"], "even_odd_versions": True}
            }
        }
    }
    # Should be filtered due to explicit exclusion
    assert is_version_ignored(attrs, "1.0.0") is True
    # Should be filtered due to odd minor version
    assert is_version_ignored(attrs, "1.1.0") is True
    # Should not be filtered (even minor, not excluded)
    assert is_version_ignored(attrs, "1.2.0") is False


def test_empty_attrs():
    """Test behavior with empty or missing attributes."""
    assert is_version_ignored({}, "1.2.3") is False
    assert is_version_ignored({"conda-forge.yml": {}}, "1.2.3") is False
    assert is_version_ignored({"conda-forge.yml": {"bot": {}}}, "1.2.3") is False


def test_filter_version_basic():
    """Test basic filter_version functionality."""
    attrs_no_filter = {"conda-forge.yml": {"bot": {"version_updates": {}}}}
    assert filter_version(attrs_no_filter, "1.2.3") == "1.2.3"
    assert filter_version(attrs_no_filter, False) is False

    attrs_exclude = {
        "conda-forge.yml": {"bot": {"version_updates": {"exclude": ["1.2.3"]}}}
    }
    assert filter_version(attrs_exclude, "1.2.3") is False
    assert filter_version(attrs_exclude, "1.2.4") == "1.2.4"


def test_filter_version_odd_even():
    """Test filter_version with odd/even filtering."""
    attrs = {
        "conda-forge.yml": {"bot": {"version_updates": {"even_odd_versions": True}}}
    }
    assert filter_version(attrs, "1.1.0") is False  # Odd minor -> filtered
    assert filter_version(attrs, "1.2.0") == "1.2.0"  # Even minor -> kept
