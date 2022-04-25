from contextlib import contextmanager

from xonsh.execer import Execer
from xonsh.environ import Env
from typing import Iterator

env: Env
execer: Execer

def eval_xonsh(inp: str) -> str: ...
