from concurrent.futures import as_completed
import numpy as np
from conda_forge_tick.executors import executor

import pytest


def _square(x):
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
