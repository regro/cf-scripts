# cf-scripts
[![tests](https://github.com/regro/cf-scripts/workflows/tests/badge.svg)](https://github.com/regro/cf-scripts/actions?query=workflow%3Atests)

Conda-Forge dependency graph tracker and auto ticker

## Autotick Bot Status and PRs
pull requests: [regro-cf-autotick-bot's PRs](https://github.com/pulls?utf8=%E2%9C%93&q=is%3Aopen+is%3Apr+author%3Aregro-cf-autotick-bot+archived%3Afalse+)

autotick bot status: [![bot](https://github.com/regro/autotick-bot/workflows/bot/badge.svg)](https://github.com/regro/autotick-bot/actions?query=workflow%3Abot)

## Setup

Below are instructions for setting up a local installation for testing. They
assume that you have conda installed and conda-forge is in your channel list.

```
conda create -y -n cf --file requirements/run --file requirements/test ipython
source activate cf
python setup.py install
pre-commit run -a
coverage run run_tests.py
```

## Notes
- seems that pytest-xdist and @flaky decorator dont play nicely. This error crops up but only for tests marked `@flaky`
```

[gw1] [ 50%] PASSED tests/test_cross_compile.py::test_cross_python_no_build
INTERNALERROR> Traceback (most recent call last):
INTERNALERROR>   File "/home/ericdill/mambaforge/envs/cfbot/lib/python3.9/site-packages/_pytest/main.py", line 270, in wrap_session
INTERNALERROR>     session.exitstatus = doit(config, session) or 0
INTERNALERROR>   File "/home/ericdill/mambaforge/envs/cfbot/lib/python3.9/site-packages/_pytest/main.py", line 324, in _main
INTERNALERROR>     config.hook.pytest_runtestloop(session=session)
INTERNALERROR>   File "/home/ericdill/mambaforge/envs/cfbot/lib/python3.9/site-packages/pluggy/_hooks.py", line 265, in __call__
INTERNALERROR>     return self._hookexec(self.name, self.get_hookimpls(), kwargs, firstresult)
INTERNALERROR>   File "/home/ericdill/mambaforge/envs/cfbot/lib/python3.9/site-packages/pluggy/_manager.py", line 80, in _hookexec
INTERNALERROR>     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR>   File "/home/ericdill/mambaforge/envs/cfbot/lib/python3.9/site-packages/pluggy/_callers.py", line 60, in _multicall
INTERNALERROR>     return outcome.get_result()
INTERNALERROR>   File "/home/ericdill/mambaforge/envs/cfbot/lib/python3.9/site-packages/pluggy/_result.py", line 60, in get_result
INTERNALERROR>     raise ex[1].with_traceback(ex[2])
INTERNALERROR>   File "/home/ericdill/mambaforge/envs/cfbot/lib/python3.9/site-packages/pluggy/_callers.py", line 39, in _multicall
INTERNALERROR>     res = hook_impl.function(*args)
INTERNALERROR>   File "/home/ericdill/mambaforge/envs/cfbot/lib/python3.9/site-packages/xdist/dsession.py", line 115, in pytest_runtestloop
INTERNALERROR>     self.loop_once()
INTERNALERROR>   File "/home/ericdill/mambaforge/envs/cfbot/lib/python3.9/site-packages/xdist/dsession.py", line 138, in loop_once
INTERNALERROR>     call(**kwargs)
INTERNALERROR>   File "/home/ericdill/mambaforge/envs/cfbot/lib/python3.9/site-packages/xdist/dsession.py", line 283, in worker_runtest_protocol_complete
INTERNALERROR>     self.sched.mark_test_complete(node, item_index, duration)
INTERNALERROR>   File "/home/ericdill/mambaforge/envs/cfbot/lib/python3.9/site-packages/xdist/scheduler/load.py", line 151, in mark_test_complete
INTERNALERROR>     self.node2pending[node].remove(item_index)
INTERNALERROR> ValueError: list.remove(x): x not in list
```
