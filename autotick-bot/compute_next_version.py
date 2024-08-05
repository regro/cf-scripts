import datetime
import subprocess

# get the current date for tagging below
now = datetime.datetime.utcnow()

# get the most recent tag
res = subprocess.run(
    ["git", "describe", "--tags", "--abbrev=0"],
    capture_output=True,
    text=True,
)

if res.returncode != 0:
    # no tags so compute the first version
    new_version = f"{now.year}.{now.month}.0"
else:
    # we have a tag so bump
    curr_version = res.stdout.strip()

    # figure out if we bump the major, minor or patch version
    major_minor, patch = curr_version.rsplit(".", 1)
    now_major_minor = f"{now.year}.{now.month}"
    if major_minor == now_major_minor:
        new_version = f"{major_minor}.{int(patch) + 1}"
    else:
        new_version = f"{now_major_minor}.0"

print(new_version, flush=True)
