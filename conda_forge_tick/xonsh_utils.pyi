from contextlib import contextmanager

from xonsh.execer import Execer
from xonsh.environ import Env

env: Env
execer: Execer

def eval_xonsh(inp: str) -> str:
    ...

@contextmanager
def indir(path: str):
    pass
