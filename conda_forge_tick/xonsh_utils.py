import copy

from xonsh.execer import Execer
from xonsh.environ import Env
from xonsh.lib.os import indir
from xonsh.__amalgam__ import CommandPipeline
import builtins

env: Env = builtins.__xonsh__.env  # type: ignore
execer: Execer = builtins.__xonsh__.execer  # type: ignore


def eval_xonsh(inp: str) -> str:
    import inspect

    frame = inspect.stack()[1][0]
    glbs = frame.f_globals
    locs = frame.f_locals

    res = execer.eval(f"!({inp})", glbs=glbs, locs=locs)
    if isinstance(res, CommandPipeline):
        return copy.copy(res.out.strip())
    else:
        return res
