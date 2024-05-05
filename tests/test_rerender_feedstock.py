import os
import subprocess
import tempfile

from conda_forge_tick.os_utils import pushd
from conda_forge_tick.rerender_feedstock import rerender_feedstock_local


def test_rerender_feedstock_stderr(capfd):
    with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
        subprocess.run(
            [
                "git",
                "clone",
                "https://github.com/conda-forge/conda-forge-feedstock-check-solvable-feedstock.git",
            ]
        )
        # make sure rerender happens
        with pushd("conda-forge-feedstock-check-solvable-feedstock"):
            cmds = [
                ["git", "rm", "-f", ".gitignore"],
                ["git", "rm", "-rf", ".scripts"],
                ["git", "config", "user.email", "conda@conda.conda"],
                ["git", "config", "user.name", "conda c. conda"],
                ["git", "commit", "-m", "test commit"],
            ]
            for cmd in cmds:
                subprocess.run(
                    cmd,
                    check=True,
                )

        try:
            msg = rerender_feedstock_local(
                os.path.join(tmpdir, "conda-forge-feedstock-check-solvable-feedstock"),
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
            [
                "git",
                "clone",
                "https://github.com/conda-forge/conda-forge-feedstock-check-solvable-feedstock.git",
            ]
        )
        # make sure rerender happens
        with pushd("conda-forge-feedstock-check-solvable-feedstock"):
            cmds = [
                ["git", "rm", "-f", ".gitignore"],
                ["git", "rm", "-rf", ".scripts"],
                ["git", "config", "user.email", "conda@conda.conda"],
                ["git", "config", "user.name", "conda c. conda"],
                ["git", "commit", "-m", "test commit"],
            ]
            for cmd in cmds:
                subprocess.run(
                    cmd,
                    check=True,
                )

        msg = rerender_feedstock_local(
            os.path.join(tmpdir, "conda-forge-feedstock-check-solvable-feedstock"),
        )
        assert msg is not None

        # check that things are staged in git
        with pushd("conda-forge-feedstock-check-solvable-feedstock"):
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
