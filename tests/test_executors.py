import time
from concurrent.futures import as_completed

import numpy as np
import pytest

from conda_forge_tick.executors import executor


def _square_with_lock(x):
    from conda_forge_tick.executors import (
        GIT_LOCK_DASK,
        GIT_LOCK_PROCESS,
        GIT_LOCK_THREAD,
    )

    with GIT_LOCK_THREAD, GIT_LOCK_PROCESS, GIT_LOCK_DASK:
        with GIT_LOCK_THREAD, GIT_LOCK_PROCESS, GIT_LOCK_DASK:
            time.sleep(0.01)
            return x * x


def _square_with_lock_git_operation(x):
    from conda_forge_tick.executors import lock_git_operation

    with lock_git_operation():
        with lock_git_operation():
            time.sleep(0.01)
            return x * x


def _square(x):
    time.sleep(0.01)
    return x * x


@pytest.mark.parametrize(
    "kind",
    [
        "thread",
        "process",
        "dask",
        "dask-process",
        "dask-thread",
    ],
)
def test_executor(kind):
    seed = 10
    rng = np.random.RandomState(seed=seed)
    nums = rng.uniform(size=1000)
    tot = np.sum(nums * nums)

    par_tot = 0
    with executor(kind, max_workers=4) as exe:
        futs = [exe.submit(_square, num) for num in nums]
        for fut in as_completed(futs):
            par_tot += fut.result()

    assert np.allclose(tot, par_tot)


@pytest.mark.parametrize(
    "locked_square_function",
    [_square_with_lock, _square_with_lock_git_operation],
)
@pytest.mark.parametrize(
    "kind",
    [
        "thread",
        "process",
        "dask",
        "dask-process",
        "dask-thread",
    ],
)
def test_executor_locking(kind, locked_square_function):
    seed = 10
    rng = np.random.RandomState(seed=seed)
    nums = rng.uniform(size=100)
    tot = np.sum(nums * nums)

    par_tot = 0
    t0 = time.time()
    with executor(kind, max_workers=4) as exe:
        futs = [exe.submit(_square, num) for num in nums]
        for fut in as_completed(futs):
            par_tot += fut.result()
    t0 = time.time() - t0
    assert np.allclose(tot, par_tot)

    par_tot = 0
    t0lock = time.time()
    with executor(kind, max_workers=4) as exe:
        futs = [exe.submit(locked_square_function, num) for num in nums]
        for fut in as_completed(futs):
            par_tot += fut.result()
    t0lock = time.time() - t0lock
    assert np.allclose(tot, par_tot)

    print(f"{kind} times:", t0, t0lock, flush=True)
    assert t0lock > t0
