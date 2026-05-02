from unittest.mock import Mock, patch

import pytest

from conda_forge_tick.update_sources import CratesIO


class TestCratesIOTierDirectory:
    def test_four_or_more_characters(self):
        pkg = "rasusa"

        actual = CratesIO._tier_directory(pkg)
        expected = "ra/su/rasusa"

        assert actual == expected

    def test_four_characters(self):
        pkg = "psdm"

        actual = CratesIO._tier_directory(pkg)
        expected = "ps/dm/psdm"

        assert actual == expected

    def test_three_characters(self):
        pkg = "syn"

        actual = CratesIO._tier_directory(pkg)
        expected = "3/s/syn"

        assert actual == expected

    def test_two_characters(self):
        pkg = "it"

        actual = CratesIO._tier_directory(pkg)
        expected = "2/it"

        assert actual == expected

    def test_one_character(self):
        pkg = "a"

        actual = CratesIO._tier_directory(pkg)
        expected = "1/a"

        assert actual == expected

    def test_empty_string(self):
        pkg = ""

        with pytest.raises(ValueError):
            CratesIO._tier_directory(pkg)


class TestCratesIOGetVersion:
    def test_valid_package(self):
        # as far as I can tell, this package has not had a new version in the last 9
        # years, so it should be safe to use for testing as we don't expect the version
        # to change
        pkg = "gopher"
        tier = CratesIO._tier_directory(pkg)
        url = f"https://index.crates.io/{tier}"

        actual = CratesIO().get_version(url, {})
        expected = "0.0.3"

        assert actual == expected

    def test_invalid_package(self):
        pkg = "shdfbshbvjhbvhsbhsb"
        tier = CratesIO._tier_directory(pkg)
        url = f"https://index.crates.io/{tier}"

        result = CratesIO().get_version(url, {})
        assert result is None

    @patch("conda_forge_tick.update_sources.requests.get")
    def test_empty_package(self, mock_get):
        pkg = "syn"
        tier = CratesIO._tier_directory(pkg)
        url = f"https://index.crates.io/{tier}"

        # Mock response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.text = '{"name": "syn"}'
        mock_get.return_value = mock_response

        result = CratesIO().get_version(url, {})
        assert result is None
