import logging
import os
import subprocess
import sys
import tempfile
import time
from threading import Thread

from conda_forge_tick.os_utils import pushd, sync_dirs
from conda_forge_tick.utils import run_container_task

logger = logging.getLogger(__name__)


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
        tmp_feedstock_dir = os.path.join(tmpdir, os.path.basename(feedstock_dir))
        sync_dirs(
            feedstock_dir, tmp_feedstock_dir, ignore_dot_git=True, update_git=False
        )

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
            if data["commit_message"] is not None:
                sync_dirs(
                    tmp_feedstock_dir,
                    feedstock_dir,
                    ignore_dot_git=True,
                    update_git=True,
                )

    return data["commit_message"]


# code to stream i/o like tee from this SO post
# https://stackoverflow.com/questions/2996887/how-to-replicate-tee-behavior-in-python-when-using-subprocess
# but it is working and changed a bit to handle two streams


class _StreamToStderr(Thread):
    def __init__(self, *buffers, timeout=None):
        super().__init__()
        self.buffers = list(buffers)
        self.lines = []
        self.timeout = timeout

    def run(self):
        t0 = time.time()
        while True and (self.timeout is None or time.time() - t0 < self.timeout):
            last_lines = []
            for buffer in self.buffers:
                try:
                    line = buffer.readline()
                except Exception:
                    pass
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
    out_thread = _StreamToStderr(proc.stdout, proc.stderr, timeout=timeout)
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
        # ret = subprocess.run(
        #     [
        #         "conda",
        #         "smithy",
        #         "rerender",
        #         "--no-check-uptodate",
        #         "--temporary-directory",
        #         tmpdir,
        #     ],
        #     stdout=subprocess.PIPE,
        #     stderr=subprocess.STDOUT,
        #     text=True,
        #     timeout=timeout,
        # )
        # print(ret.stdout, flush=True, file=sys.stderr)
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
        raise RuntimeError(f"Failed to rerender.\noutput: {ret.stdout}\n")

    commit_message = None
    for line in ret.stdout.split("\n"):
        if '    git commit -m "MNT: ' in line:
            commit_message = line.split('git commit -m "')[1].strip()[:-1]

    return commit_message
