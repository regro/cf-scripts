import datetime
import glob
import logging
import os
import pprint
import subprocess
import tempfile

from conda_forge_tick.lazy_json_backends import (
    CF_TICK_GRAPH_DATA_HASHMAPS,
    LAZY_JSON_BACKENDS,
    get_sharded_path,
)

from .cli_context import CliContext

logger = logging.getLogger(__name__)

CF_TICK_GRAPH_DATA_BACKUP_BACKEND = os.environ.get(
    "CF_TICK_GRAPH_DATA_BACKUP_BACKEND",
    "file",
)


def make_lazy_json_backup(verbose=False):
    ts = str(int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp()))
    slink = f"cf_graph_{ts}"
    try:
        subprocess.run(
            ["ln", "-s", ".", slink],
            check=True,
            capture_output=not verbose,
        )
        backend = LAZY_JSON_BACKENDS["file"]()
        with tempfile.TemporaryDirectory() as tmpdir:
            logger.info("gathering files for backup")
            with open(os.path.join(tmpdir, "files.txt"), "w") as fp:
                for hashmap in CF_TICK_GRAPH_DATA_HASHMAPS + ["lazy_json"]:
                    nodes = backend.hkeys(hashmap)
                    for node in nodes:
                        fp.write(
                            os.path.join(
                                slink,
                                get_sharded_path(f"{hashmap}/{node}.json"),
                            )
                            + "\n",
                        )

            logger.info("compressing lazy json disk cache")
            subprocess.run(
                [
                    "tar",
                    "--zstd",
                    "-cvf",
                    f"cf_graph_{ts}.tar.zstd",
                    "-T",
                    os.path.join(tmpdir, "files.txt"),
                ],
                check=True,
                capture_output=not verbose,
            )
    finally:
        subprocess.run(
            ["rm", "-f", slink],
            check=True,
            capture_output=not verbose,
        )

    return f"cf_graph_{ts}.tar.zstd"


def prune_timestamps(
    timestamps,
    maxsize=4000,
    sizeper=50,
    nhours=24,
    ndays=7,
    nweeks=8,
    nmonths=24,
):
    tokeep = {}

    one_hour = datetime.timedelta(hours=1)
    one_day = datetime.timedelta(days=1)
    one_week = datetime.timedelta(weeks=1)
    one_month = datetime.timedelta(weeks=4)

    now = datetime.datetime.now(tz=datetime.timezone.utc)

    tot = 0
    for ts in sorted(timestamps)[::-1]:
        dt = datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc)
        for i in range(nhours):
            key = f"h{i}"
            dt_high = now - i * one_hour
            dt_low = dt_high - one_hour
            if dt >= dt_low and dt <= dt_high and key not in tokeep and tot < maxsize:
                tokeep[key] = int(ts)
                tot = len(set(tokeep.values())) * sizeper
                break

        for i in range(ndays):
            key = f"d{i}"
            dt_high = now - i * one_day
            dt_low = dt_high - one_day
            if dt >= dt_low and dt <= dt_high and key not in tokeep and tot < maxsize:
                tokeep[key] = int(ts)
                tot = len(set(tokeep.values())) * sizeper
                break

        for i in range(nweeks):
            key = f"w{i}"
            dt_high = now - i * one_week
            dt_low = dt_high - one_week
            if dt >= dt_low and dt <= dt_high and key not in tokeep and tot < maxsize:
                tokeep[key] = int(ts)
                tot = len(set(tokeep.values())) * sizeper
                break

        for i in range(nmonths):
            key = f"m{i}"
            dt_high = now - i * one_month
            dt_low = dt_high - one_month
            if dt >= dt_low and dt <= dt_high and key not in tokeep and tot < maxsize:
                tokeep[key] = int(ts)
                tot = len(set(tokeep.values())) * sizeper
                break

    if len(tokeep) == 0 and len(ts) > 0:
        tokeep["keep_one"] = int(sorted(timestamps)[::-1][0])

    return tokeep


def get_current_backup_filenames():
    if CF_TICK_GRAPH_DATA_BACKUP_BACKEND == "file":
        backups = glob.glob("cf_graph_*.tar.zstd")
        return [os.path.basename(b) for b in backups]
    else:
        raise RuntimeError(
            "CF_TICK_GRAPH_DATA_BACKUP_BACKEND %s not recognized!"
            % CF_TICK_GRAPH_DATA_BACKUP_BACKEND,
        )


def remove_backup(fname):
    if CF_TICK_GRAPH_DATA_BACKUP_BACKEND == "file":
        try:
            os.remove(fname)
        except Exception:
            pass
    else:
        raise RuntimeError(
            "CF_TICK_GRAPH_DATA_BACKUP_BACKEND %s not recognized!"
            % CF_TICK_GRAPH_DATA_BACKUP_BACKEND,
        )


def save_backup(fname):
    if CF_TICK_GRAPH_DATA_BACKUP_BACKEND == "file":
        pass
    else:
        raise RuntimeError(
            "CF_TICK_GRAPH_DATA_BACKUP_BACKEND %s not recognized!"
            % CF_TICK_GRAPH_DATA_BACKUP_BACKEND,
        )


def main_backup(ctx: CliContext):
    def _name_to_ts(b):
        return int(b.split(".")[0].split("_")[-1])

    if not ctx.dry_run:
        logger.info("making lazy json backup")
        latest_backup = make_lazy_json_backup()
        curr_fnames = get_current_backup_filenames()
        all_fnames = set(curr_fnames) | {latest_backup}
        all_timestamps = [_name_to_ts(b) for b in all_fnames]
        tsdict = prune_timestamps(all_timestamps)
        logger.info("backups to keep:\n%s", pprint.pformat(tsdict, sort_dicts=False))

        timestamps_to_keep = set(tsdict.values())
        for bup in all_fnames:
            if _name_to_ts(bup) not in timestamps_to_keep:
                try:
                    logger.info("removing backup %s", bup)
                    remove_backup(bup)
                except Exception:
                    pass
            else:
                logger.info("saving backup %s", bup)
                if bup not in curr_fnames:
                    save_backup(bup)
