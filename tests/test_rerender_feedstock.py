import os
import subprocess
import tempfile

from conda_forge_tick.os_utils import pushd
from conda_forge_tick.rerender_feedstock import rerender_feedstock_local


def test_rerender_feedstock_stderr(capfd):
    with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
        subprocess.run(
            ["git", "clone", "https://github.com/conda-forge/ngmix-feedstock.git"]
        )
        # make sure rerender happens
        with pushd("ngmix-feedstock"):
            subprocess.run(
                ["git", "rm", "-f", ".gitignore"],
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "test commit"],
                check=True,
            )

        try:
            msg = rerender_feedstock_local(
                os.path.join(tmpdir, "ngmix-feedstock"),
            )
        finally:
            captured = capfd.readouterr()
            print(f"out: {captured.out}\nerr: {captured.err}")

        assert "git commit -m " in captured.err
        assert msg is not None, f"msg: {msg}\nout: {captured.out}\nerr: {captured.err}"
        assert msg.startswith(
            "MNT:"
        ), f"msg: {msg}\nout: {captured.out}\nerr: {captured.err}"


def test_rerender_feedstock_git_staged():
    with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
        subprocess.run(
            ["git", "clone", "https://github.com/conda-forge/ngmix-feedstock.git"]
        )
        # make sure rerender happens
        with pushd("ngmix-feedstock"):
            subprocess.run(
                ["git", "rm", "-f", ".gitignore"],
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "test commit"],
                check=True,
            )

        msg = rerender_feedstock_local(
            os.path.join(tmpdir, "ngmix-feedstock"),
        )
        assert msg is not None

        # check that things are staged in git
        with pushd("ngmix-feedstock"):
            ret = subprocess.run(
                ["git", "diff", "--name-only", "--staged"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=True,
            )
        found_it = False
        for line in ret.stdout.split("\n"):
            if ".gitignore" in line:
                found_it = True
                break
        assert found_it, ret.stdout
