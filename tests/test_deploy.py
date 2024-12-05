import os
import tempfile

import pytest

from conda_forge_tick.deploy import _parse_gh_conflicts
from conda_forge_tick.os_utils import pushd


@pytest.mark.parametrize(
    "output,fnames",
    [
        ("", []),
        (
            """\
error: The following untracked working tree files would be overwritten by merge:
	pr_info/8/1/0/1/f/devtools.json
Please move or remove them before you merge.
Aborting
Merge with strategy recursive failed.
""",
            ["pr_info/8/1/0/1/f/devtools.json"],
        ),
    ],
)
def test_deploy_parse_gh_conflicts(output, fnames):
    with tempfile.TemporaryDirectory() as tmpdir, pushd(str(tmpdir)):
        for fname in fnames:
            os.makedirs(os.path.dirname(fname), exist_ok=True)
            with open(fname, "w") as f:
                f.write("")
        assert _parse_gh_conflicts(output) == fnames
