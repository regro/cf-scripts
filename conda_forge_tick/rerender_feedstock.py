import os
import shutil
import subprocess
import sys
import tempfile
from threading import Thread

from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import run_container_task


def rerender_feedstock(feedstock_dir, timeout=900, use_container=True):
    """Rerender a feedstock.

    Parameters
    ----------
    feedstock_dir : str
        The path to the feedstock directory.
    timeout : int, optional
        The timeout for the rerender in seconds, by default 900.
    use_container
        Whether to use a container to run the parsing.
        If None, the function will use a container if the environment
        variable `CF_TICK_IN_CONTAINER` is 'false'. This feature can be
        used to avoid container in container calls.

    Returns
    -------
    str
        The commit message for the rerender. If None, the rerender didn't change anything.
    """

    in_container = os.environ.get("CF_TICK_IN_CONTAINER", "false") == "true"
    if use_container is None:
        use_container = not in_container

    if use_container and not in_container:
        return rerender_feedstock_containerized(
            feedstock_dir,
            timeout=timeout,
        )
    else:
        return rerender_feedstock_local(
            feedstock_dir,
            timeout=timeout,
        )


def rerender_feedstock_containerized(feedstock_dir, timeout=900):
    """Rerender a feedstock.

    **This function runs the rerender in a container.**

    Parameters
    ----------
    feedstock_dir : str
        The path to the feedstock directory.
    timeout : int, optional
        The timeout for the rerender in seconds, by default 900.

    Returns
    -------
    str
        The commit message for the rerender. If None, the rerender didn't change anything.
    """
    args = []

    if timeout is not None:
        args += ["--timeout", str(timeout)]

    with tempfile.TemporaryDirectory() as tmpdir:
        shutil.copytree(feedstock_dir, tmpdir, dirs_exist_ok=True)
        shutil.rmtree(os.path.join(tmpdir, ".git"))
        os.remove(os.path.join(tmpdir, ".gitignore"))

        os.chmod(tmpdir, 0o777)
        subprocess.run(["chmod", "-R", "777", tmpdir], check=True, capture_output=True)

        try:
            data = run_container_task(
                "rerender-feedstock",
                args,
                mount_readonly=False,
                mount_dir=tmpdir,
            )
        except Exception as e:
            raise e
        else:
            os.chmod(tmpdir, 0o777)
            subprocess.run(["chmod", "-R", "777", tmpdir], check=True, capture_output=True)
            shutil.rmtree(os.path.join(tmpdir, ".git"))
            shutil.copytree(tmpdir, feedstock_dir, dirs_exist_ok=True)

    return data["commit_message"]


# code to stream i/o like tee from this SO post
# https://stackoverflow.com/questions/2996887/how-to-replicate-tee-behavior-in-python-when-using-subprocess
# but it is working and changed a bit to handle two streams


class _StreamToStderr(Thread):
    def __init__(self, *buffers):
        super().__init__()
        self.buffers = list(buffers)
        self.lines = []

    def run(self):
        while True:
            last_lines = []
            for buffer in self.buffers:
                line = buffer.readline()
                last_lines.append(line)
                self.lines.append(line)

                sys.stderr.write(line)
                sys.stderr.flush()

            if all(line == "" for line in last_lines):
                break

        self.output = "".join(self.lines)


def _subprocess_run_tee(args, timeout=None):
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out_thread = _StreamToStderr(proc.stdout, proc.stderr)
    out_thread.start()
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()

    out_thread.join()
    for line in (err + out).splitlines():
        sys.stderr.write(line + "\n")
        sys.stderr.flush()

    proc.stdout = out_thread.output + out + err
    return proc


def rerender_feedstock_local(feedstock_dir, timeout=900):
    """Rerender a feedstock.

    **This function runs the rerender in a container.**

    Parameters
    ----------
    feedstock_dir : str
        The path to the feedstock directory.
    timeout : int, optional
        The timeout for the rerender in seconds, by default 900.

    Returns
    -------
    str
        The commit message for the rerender. If None, the rerender didn't change anything.
    """
    with (
        pushd(feedstock_dir),
        tempfile.TemporaryDirectory() as tmpdir,
    ):
        ret = _subprocess_run_tee(
            [
                "conda",
                "smithy",
                "rerender",
                "--no-check-uptodate",
                "--temporary-directory",
                tmpdir,
            ],
            timeout=timeout,
        )

    if ret.returncode != 0:
        raise RuntimeError(
            f"Failed to rerender.\n" f"stdout: {ret.stdout}\n" f"stderr: {ret.stderr}"
        )

    commit_message = None
    for line in ret.stdout.split("\n"):
        if '    git commit -m "MNT: ' in line:
            commit_message = line.split('git commit -m "')[1].strip()[:-1]

    return commit_message
