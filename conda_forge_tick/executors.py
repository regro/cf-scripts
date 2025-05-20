import contextlib
import logging
import multiprocessing
import typing
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from threading import RLock as TRLock

from distributed import Lock as DaskLock


class DummyLock:
    def __enter__(self, *args, **kwargs):
        return self

    def __exit__(self, *args, **kwargs):
        pass


GIT_LOCK_THREAD = TRLock()
GIT_LOCK_PROCESS = DummyLock()
GIT_LOCK_DASK = DummyLock()


@contextlib.contextmanager
def lock_git_operation():
    """
    Get a context manager to lock git operations - it can be acquired once per thread, once per process,
    and once per dask worker.
    Note that this is a reentrant lock, so it can be acquired multiple times by the same thread/process/worker.
    """
    with GIT_LOCK_THREAD, GIT_LOCK_PROCESS, GIT_LOCK_DASK:
        yield


logger = logging.getLogger(__name__)


class DaskRLock(DaskLock):
    """A reentrant lock for dask that is always blocking and never times out."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rcount = 0
        self._rdata = None

    def acquire(self, *args):
        self._rcount += 1

        if self._rcount == 1:
            self._rdata = super().acquire(blocking=True, timeout=None)

        return self._rdata

    def release(self):
        if self._rcount == 0:
            raise RuntimeError("Lock not acquired so cannot be released!")

        self._rcount -= 1

        if self._rcount == 0:
            self._rdata = None
            return super().release()
        else:
            return None


def _init_process(lock):
    global GIT_LOCK_PROCESS
    GIT_LOCK_PROCESS = lock


def _init_dask(lock):
    global GIT_LOCK_DASK
    # it appears we have to construct the lock by name instead
    # of passing the object itself
    # otherwise dask uses a regular lock
    GIT_LOCK_DASK = DaskRLock(name=lock)


@contextlib.contextmanager
def executor(kind: str, max_workers: int, daemon=True) -> typing.Iterator[Executor]:
    """General purpose utility to get an executor with its as_completed handler.

    This allows us to easily use other executors as needed.
    """
    global GIT_LOCK_DASK
    global GIT_LOCK_PROCESS

    if kind == "thread":
        with ThreadPoolExecutor(max_workers=max_workers) as pool_t:
            yield pool_t
    elif kind == "process":
        m = multiprocessing.Manager()
        lock = m.RLock()
        with ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=_init_process,
            initargs=(lock,),
        ) as pool_p:
            yield pool_p
        GIT_LOCK_PROCESS = DummyLock()
    elif kind in ["dask", "dask-process", "dask-thread"]:
        import dask
        import distributed
        from distributed.cfexecutor import ClientExecutor

        processes = kind == "dask" or kind == "dask-process"

        with dask.config.set({"distributed.worker.daemon": daemon}):
            with distributed.LocalCluster(
                n_workers=max_workers,
                processes=processes,
            ) as cluster:
                with distributed.Client(cluster) as client:
                    client.run(_init_dask, "cftick")
                    yield ClientExecutor(client)
                GIT_LOCK_DASK = DummyLock()
    else:
        raise NotImplementedError("That kind is not implemented")
