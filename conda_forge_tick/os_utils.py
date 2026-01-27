import contextlib
import copy
import logging
import os
import subprocess
import sys
import tempfile
import time
from threading import Event, Thread

logger = logging.getLogger(__name__)


# https://stackoverflow.com/questions/6194499/pushd-through-os-system
@contextlib.contextmanager
def pushd(new_dir: str):
    previous_dir = os.getcwd()
    os.chdir(new_dir)
    try:
        yield
    finally:
        os.chdir(previous_dir)


@contextlib.contextmanager
def override_env(name, value):
    """Override an environment variable temporarily."""
    old = os.environ.get(name)
    try:
        os.environ[name] = value
        yield
    finally:
        if old is None:
            del os.environ[name]
        else:
            os.environ[name] = old


def eval_cmd(cmd: list[str], **kwargs) -> str:
    """Run a command capturing stdout.

    stderr is printed for debugging
    any kwargs are added to the env
    """
    env = copy.deepcopy(os.environ)
    timeout = kwargs.pop("timeout", None)
    env.update(kwargs)
    c = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        env=env,
        timeout=timeout,
    )
    if c.returncode != 0:
        print(c.stdout.decode("utf-8"), flush=True)
        c.check_returncode()

    return c.stdout.decode("utf-8")


def clean_disk_space(ci_service: str = "github-actions") -> None:
    """Clean up disk space on CI services.

    Parameters
    ----------
    ci_service : str, optional
        The CI service to clean up disk space for. Currently only "github-actions" is supported.
        Default is "github-actions".

    Raises
    ------
    ValueError
        If the provided ci_service is not recognized.
    """
    with tempfile.TemporaryDirectory() as tempdir, pushd(tempdir):
        with open("clean_disk.sh", "w") as f:
            if ci_service == "github-actions":
                f.write(
                    """\
  #!/bin/bash

  # clean disk space
  sudo mkdir -p /opt/empty_dir || true
  for d in \
  /opt/ghc \
  /opt/hostedtoolcache \
  /usr/lib/jvm \
  /usr/local/.ghcup \
  /usr/local/lib/android \
  /usr/local/share/powershell \
  /usr/share/dotnet \
  /usr/share/swift \
  ; do
    sudo rsync --stats -a --delete /opt/empty_dir/ $d || true
  done
  # dpkg does not fail if the package is not installed
  sudo dpkg --remove -y -f firefox \
                          google-chrome-stable \
                          microsoft-edge-stable
  sudo apt-get autoremove -y >& /dev/null
  sudo apt-get autoclean -y >& /dev/null
  sudo docker image prune --all --force
  df -h
"""
                )
            else:
                raise ValueError(f"Unknown CI service: {ci_service}")

            subprocess.run(["bash", "clean_disk.sh"])


class _StreamToStderr(Thread):
    def __init__(self, buffer, stop_event, timeout=None):
        super().__init__()
        self.buffer = buffer
        self.lines = []
        self.timeout = timeout
        self.stop_event = stop_event

    def run(self):
        t0 = time.time()
        while True:
            if self.stop_event.is_set():
                break

            if self.timeout is not None and time.time() - t0 > self.timeout:
                break

            try:
                line = self.buffer.readline()
            except Exception:
                line = ""

            if line:
                self.lines.append(line)
                sys.stderr.write(line)
                sys.stderr.flush()

        self.output = "".join(self.lines)


def run_subprocess_with_tee(args, timeout=None):
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    os.set_blocking(proc.stdout.fileno(), False)  # type: ignore
    os.set_blocking(proc.stderr.fileno(), False)  # type: ignore

    stop_event = Event()
    threads = [
        _StreamToStderr(proc.stdout, stop_event, timeout=timeout),
        _StreamToStderr(proc.stderr, stop_event, timeout=timeout),
    ]
    for out_thread in threads:
        out_thread.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
    finally:
        stop_event.set()
        for out_thread in threads:
            out_thread.join()

        try:
            out, err = proc.communicate(timeout=30)
        except Exception:
            out, err = "", ""

    for line in (err + out).splitlines():
        sys.stderr.write(line + "\n")
        sys.stderr.flush()

    final_out = ""
    for out_thread in threads:
        final_out += out_thread.output
    proc.stdout = final_out + out + err  # type: ignore

    return subprocess.CompletedProcess(
        args=args,
        returncode=proc.returncode,
        stdout=final_out + out + err,
        stderr=None,
    )
