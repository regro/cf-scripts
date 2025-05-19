import functools
import hashlib
import math
import time
from multiprocessing import Pipe, Process

import requests


def _hash_url(url, hash_type, progress=False, conn=None, timeout=None):
    _hash = None
    try:
        ha = getattr(hashlib, hash_type)()

        timedout = False
        t0 = time.time()

        resp = requests.get(url, stream=True, timeout=timeout or 10)

        if timeout is not None:
            if time.time() - t0 > timeout:
                timedout = True

        if resp.status_code == 200 and not timedout:
            if "Content-length" in resp.headers:
                num = math.ceil(float(resp.headers["Content-length"]) / 8192)
            elif resp.url != url:
                # redirect for download
                h = requests.head(resp.url).headers
                if "Content-length" in h:
                    num = math.ceil(float(h["Content-length"]) / 8192)
                else:
                    num = None
            else:
                num = None

            loc = 0
            for itr, chunk in enumerate(resp.iter_content(chunk_size=8192)):
                ha.update(chunk)
                if num is not None and int((itr + 1) / num * 25) > loc and progress:
                    eta = (time.time() - t0) / (itr + 1) * (num - (itr + 1))
                    loc = int((itr + 1) / num * 25)
                    print(
                        "eta {: 7.2f}s: [{}{}]".format(
                            eta, "".join(["=" * loc]), "".join([" " * (25 - loc)])
                        ),
                    )
                if timeout is not None:
                    if time.time() - t0 > timeout:
                        timedout = True

            if not timedout:
                _hash = ha.hexdigest()
            else:
                _hash = None
        else:
            _hash = None
    except requests.ConnectionError:
        _hash = None
    except Exception as e:
        _hash = (repr(e),)
    finally:
        if conn is not None:
            conn.send(_hash)
            conn.close()
        else:
            return _hash


@functools.lru_cache(maxsize=1024)
def hash_url(url, timeout=None, progress=False, hash_type="sha256"):
    """Hash a url with a timeout.

    Parameters
    ----------
    url : str
        The URL to hash.
    timeout : int, optional
        The timeout in seconds. If the operation goes longer than
        this amount, the hash will be returned as None. Set to `None`
        for no timeout.
    progress : bool, optional
        If True, show a simple progress meter.
    hash_type : str
        The kind of hash. Must be an attribute of `hashlib`.

    Returns
    -------
    hash : str or None
        The hash, possibly None if the operation timed out or the url does
        not exist.
    """  # noqa: DOC501
    _hash = None

    try:
        parent_conn, child_conn = Pipe()
        p = Process(
            target=_hash_url,
            args=(url, hash_type),
            kwargs={"progress": progress, "conn": child_conn},
        )
        p.start()
        if parent_conn.poll(timeout):
            _hash = parent_conn.recv()

        p.join(timeout=0)
        if p.exitcode != 0:
            p.terminate()
    except AssertionError as e:
        # if launched in a process we cannot use another process
        if "daemonic" in repr(e):
            _hash = _hash_url(
                url,
                hash_type,
                progress=progress,
                conn=None,
                timeout=timeout,
            )
        else:
            raise e

    if isinstance(_hash, tuple):
        # TODO: What is this? (remove noqa from above)
        raise eval(_hash[0])

    return _hash
