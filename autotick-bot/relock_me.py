import os
import shutil
import subprocess
import sys

from conda.models.match_spec import MatchSpec
from ruamel.yaml import YAML

yaml = YAML(typ="safe", pure=True)
yaml.indent(mapping=2, sequence=4, offset=2)
yaml.default_flow_style = False


def _run_cmd(cmd):
    return subprocess.run(cmd, shell=True, check=True)


def _lock_to_ver(lock, platform):
    pkg_to_ver = {}
    for pkg in lock["package"]:
        if pkg["platform"] == platform:
            pkg_to_ver[pkg["name"]] = pkg["version"]
    return pkg_to_ver


def _reformat_lockfile(lockfile):
    # load / dump the lockfile to make sure it is sorted
    # so we get nice diffs
    with open(lockfile) as f:
        new_lock = yaml.load(f)
    new_lock["package"] = sorted(
        new_lock["package"], key=lambda x: (x["name"], x["platform"])
    )
    with open(lockfile, "w") as f:
        yaml.dump(new_lock, f)

    with open(lockfile) as f:
        lines = [line.rstrip() for line in f]

    with open(lockfile, "w") as f:
        f.write("\n".join(lines) + "\n")


lockfile = sys.argv[1]

try:
    shutil.move(lockfile, lockfile + ".bak")

    print("Relocking environment.yml...", flush=True, file=sys.stderr)
    subprocess.run(
        "conda lock --file environment.yml",
        shell=True,
        check=True,
        capture_output=True,
    )

    with open("environment.yml") as f:
        envyml = yaml.load(f)

    with open(lockfile + ".bak") as f:
        old_lock = yaml.load(f)

    with open(lockfile) as f:
        new_lock = yaml.load(f)

    old_platform_pkg_to_ver = {
        platform: _lock_to_ver(old_lock, platform) for platform in envyml["platforms"]
    }

    new_platform_pkg_to_ver = {
        platform: _lock_to_ver(new_lock, platform) for platform in envyml["platforms"]
    }

    relock_tuples = {platform: [] for platform in envyml["platforms"]}
    for spec in envyml["dependencies"]:
        spec = MatchSpec(spec)
        for platform in envyml["platforms"]:
            if old_platform_pkg_to_ver[platform].get(
                spec.name
            ) != new_platform_pkg_to_ver[platform].get(spec.name):
                relock_tuples[platform].append(
                    (
                        spec.name,
                        old_platform_pkg_to_ver[platform].get(spec.name),
                        new_platform_pkg_to_ver[platform].get(spec.name),
                    )
                )

    if any(relock_tuples[platform] for platform in envyml["platforms"]):
        os.remove(lockfile + ".bak")

        _reformat_lockfile(lockfile)

        print("The following packages have been updated:\n", flush=True)
        for platform in envyml["platforms"]:
            print(f"  platform: {platform}", flush=True)
            for pkg, old_ver, new_ver in relock_tuples[platform]:
                print(f"    - {pkg}: {old_ver} -> {new_ver}", flush=True)
            print("", flush=True)
    else:
        print("No packages have been updated.", flush=True, file=sys.stderr)
        shutil.move(lockfile + ".bak", lockfile)
except Exception as e:
    if os.path.exists(lockfile + ".bak"):
        shutil.move(lockfile + ".bak", lockfile)
    raise e
