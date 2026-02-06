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
CONFLICT (modify/delete): pr_json/0/9/7/a/1/3254711106.json deleted in 930a956604b17c5fd7cada5c011eb77f4eeebe52 and modified in HEAD. Version HEAD of pr_json/0/9/7/a/1/3254711106.json left in tree.
""",
            {"pr_info/8/1/0/1/f/devtools.json"},
            {"pr_json/0/9/7/a/1/3254711106.json"},
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
