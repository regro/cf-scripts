import datetime
import subprocess

import conda_forge_tick.utils
from conda_forge_tick.lazy_json_backends import LAZY_JSON_BACKENDS, dumps
from conda_forge_tick.lazy_json_backups import (
    get_current_backup_filenames,
    make_lazy_json_backup,
    prune_timestamps,
    remove_backup,
)
from conda_forge_tick.os_utils import pushd


def test_prune_timestamps():
    ten_mins = datetime.timedelta(minutes=10)
    one_hour = datetime.timedelta(hours=1)
    one_day = datetime.timedelta(days=1)
    one_week = datetime.timedelta(weeks=1)
    one_month = datetime.timedelta(weeks=4)

    def _to_ts(dt):
        return int(dt.timestamp())

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    timestamps = [
        now - ten_mins,
        now - 2 * ten_mins,
        now - 2 * one_hour - ten_mins,
        now - one_day - one_hour,
        now - 2 * one_day - one_hour,
        now - one_week - one_day,
        now - one_week - 2 * one_day,
        now - one_week + one_day,
        now - one_month - one_week,
    ]
    timestamps = [_to_ts(t) for t in timestamps]
    res = prune_timestamps(timestamps)
    assert res["h0"] == timestamps[0]
    assert res["d0"] == timestamps[0]
    assert timestamps[1] not in res.values()
    assert res["h2"] == timestamps[2]
    assert res["d1"] == timestamps[3]
    assert res["d2"] == timestamps[4]
    assert res["w0"] == timestamps[0]
    assert res["w1"] == timestamps[5]
    assert timestamps[6] not in res.values()
    assert res["d6"] == timestamps[7]
    assert res["m0"] == timestamps[0]
    assert res["m1"] == timestamps[8]

    ts = _to_ts(now)
    timestamps = [ts - 3600 * i for i in range(100000)]
    res = prune_timestamps(timestamps)
    assert len(res) * 50 < 4000


def test_lazy_json_backends_backup(tmpdir):
    old_backend = conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS
    with pushd(tmpdir):
        try:
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = ("file",)
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                "file"
            )

            pbe = LAZY_JSON_BACKENDS["file"]()
            for hashmap in ["lazy_json", "node_attrs"]:
                for i in range(2):
                    pbe.hset(hashmap, f"node{i}", dumps({f"a{i}": i}))

            make_lazy_json_backup()

            fnames = get_current_backup_filenames()
            assert len(fnames) == 1

            subprocess.run(
                ["tar", "xf", fnames[0]],
                check=True,
                capture_output=True,
            )

            with pushd(fnames[0].split(".")[0]):
                for hashmap in ["lazy_json", "node_attrs"]:
                    for i in range(2):
                        pbe.hget(hashmap, f"node{i}") == dumps({f"a{i}": i})

            remove_backup(fnames[0])
            fnames = get_current_backup_filenames()
            assert len(fnames) == 0
        finally:
            be = LAZY_JSON_BACKENDS["file"]()
            for hashmap in ["lazy_json", "node_attrs"]:
                for i in range(2):
                    be.hdel(hashmap, [f"node{i}"])

            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_BACKENDS = (
                old_backend
            )
            conda_forge_tick.lazy_json_backends.CF_TICK_GRAPH_DATA_PRIMARY_BACKEND = (
                old_backend[0]
            )
