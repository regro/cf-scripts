import datetime
import subprocess
import sys

from conda.models.version import VersionOrder

# get the current date for tagging below
now = datetime.datetime.utcnow()

# get the most recent tag
res = subprocess.run(
    ["git", "--no-pager", "tag", "--sort=committerdate"],
    capture_output=True,
    text=True,
)

if res.returncode != 0 or (not res.stdout.strip()):
    # no tags so compute the first version
    new_version = f"{now.year}.{now.month}.0"
else:
    # we have a tag so bump
    curr_version = None
    curr_version_line = None
    for line in res.stdout.splitlines():
        line = line.strip()
        if line:
            try:
                _version = VersionOrder(line)
            except Exception:
                print(
                    f"skipping tag that is not a version: {line}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

            if curr_version is None or _version > curr_version:
                curr_version = _version
                curr_version_line = line
    assert curr_version is not None
    print(f"found current version: {curr_version_line}", file=sys.stderr, flush=True)

    # figure out if we bump the major, minor or patch version
    major_minor, patch = curr_version_line.rsplit(".", 1)
    now_major_minor = f"{now.year}.{now.month}"
    if major_minor == now_major_minor:
        new_version = f"{major_minor}.{int(patch) + 1}"
    else:
        new_version = f"{now_major_minor}.0"

print(new_version, flush=True)
