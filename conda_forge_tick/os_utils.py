import contextlib
import copy
import logging
import os
import subprocess

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
    """run a command capturing stdout

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
