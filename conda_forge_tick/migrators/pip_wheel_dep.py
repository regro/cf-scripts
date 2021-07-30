import tempfile
from typing import Any
import typing

import requests

from conda_forge_tick.migrators import MiniMigrator
from conda_forge_tick.xonsh_utils import indir

if typing.TYPE_CHECKING:
    from conda_forge_tick.migrators_types import AttrsTypedDict


class PipWheelMigrator(MiniMigrator):
    post_migration = True

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        run_reqs = attrs.get("requirements", {}).get("run", set())
        source_url = attrs.get("url") or attrs.get("source", {}).get("url")
        url_names = ["pypi.python.org", "pypi.org", "pypi.io"]
        if not any(s in source_url for s in url_names):
            return True
        if (
            not attrs.get("meta_yaml", {})
            .get("extra", {})
            .get("bot", {})
            .get("run_deps_from_wheel", False)
        ):
            return True
        return "python" not in run_reqs

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        source_url = attrs.get("url") or attrs.get("source", {}).get("url")
        version = attrs.get("new_version", "")
        if not version:
            return None
        pkg = source_url.split("/")[6]
        resp = requests.get(f"https://pypi.org/pypi/{pkg}/{version}/json")
        try:
            resp.raise_for_status()
        except:
            return None
        wheel_count = 0
        for artifact in resp.json()["urls"]:
            if artifact["packagetype"] == "bdist_wheel":
                wheel_count += 1
                wheel_url = artifact["url"]
                wheel_file = artifact["filename"]
        if wheel_count != 1:
            return None

        # parse the versions from the wheel
        wheel_packages = {}
        with tempfile.TemporaryDirectory() as tmpdir, indir(tmpdir):
            resp = requests.get(wheel_url)
            with open(wheel_file, "wb") as fp:
                for chunk in resp.iter_content(chunk_size=2 ** 16):
                    fp.write(chunk)
            import pkginfo
            import pkg_resources

            wheel_metadata = pkginfo.get_metadata(wheel_file)
            wheel_metadata.extractMetadata()
            for dep in wheel_metadata.requires_dist:
                parsed_req = pkg_resources.Requirement.parse(dep)
                # ignore extras, and markers
                wheel_packages[parsed_req.name] = str(parsed_req.specifier)

        if not wheel_packages:
            return None
        handled_packages = set()

        with indir(recipe_dir):
            with open("meta.yaml") as f:
                lines = f.readlines()
            in_reqs = False
            for i, line in enumerate(lines):
                if line.strip().startswith("requirements:"):
                    in_reqs = True
                    continue
                if in_reqs and len(line) > 0 and line[0] != " ":
                    in_reqs = False
                if not in_reqs:
                    continue
                if line.strip().startswith("run:"):
                    # This doesn't really account for comments in blocks
                    j = i + 1
                    # Find this block in the source file
                    while j < len(lines):
                        if lines[j].strip().startswith("-"):
                            spaces = len(lines[j]) - len(lines[j].lstrip())
                        elif lines[j].strip().startswith("#"):
                            pass
                        elif lines[j].strip().startswith("{%"):
                            pass
                        else:
                            break
                        j = j + 1

                    new_line = " " * spaces
                    for line_index in range(i + 1, j):
                        line = lines[line_index]
                        if not line.strip().startswith("-"):
                            continue
                        line = lines[line_index].strip().strip("-").strip()
                        pkg_name, *_ = line.split()
                        if pkg_name in wheel_packages:
                            lines[line_index] = (
                                " " * spaces
                                + "- "
                                + pkg_name
                                + " "
                                + wheel_packages[pkg_name].replace("==", "=")
                                + "\n"
                            )
                            handled_packages.add(pkg_name)

                    # There are unhandled packages.  Since these might not be on conda-forge add them,
                    # but leave them commented out
                    for pkg_name in sorted(set(wheel_packages) - handled_packages):
                        # TODO: add to pr text saying that we discoved new deps
                        new_line = (
                            " " * spaces
                            + "# - "
                            + pkg_name
                            + " "
                            + wheel_packages[pkg_name].replace("==", "=")
                            + "\n"
                        )
                        handled_packages.add(pkg_name)
                        lines.insert(j, new_line)

                    break

            with open("meta.yaml", "w") as f:
                f.write("".join(lines))
