import tempfile
import functools
from typing import Any, Dict
from ruamel.yaml import YAML
import typing

import requests

from conda_forge_tick.migrators import MiniMigrator
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import get_keys_default

if typing.TYPE_CHECKING:
    from conda_forge_tick.migrators_types import AttrsTypedDict


@functools.lru_cache()
def pypi_conda_mapping() -> Dict[str, str]:
    """Retrieves the most recent version of the pypi-conda name mapping dictionary.

    Result is a dictionary {pypi_name: conda_name}
    """
    yaml = YAML()
    content = requests.get(
        "https://raw.githubusercontent.com/regro/cf-graph-countyfair/master/mappings/pypi/grayskull_pypi_mapping.yaml",  # noqa
    ).text
    mappings = yaml.load(content)
    return {
        mapping["pypi_name"]: mapping["conda_name"] for mapping in mappings.values()
    }


class PipWheelMigrator(MiniMigrator):
    post_migration = True

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        run_reqs = attrs.get("requirements", {}).get("run", set())
        source_url = attrs.get("url") or attrs.get("source", {}).get("url")
        url_names = ["pypi.python.org", "pypi.org", "pypi.io"]
        if not any(s in source_url for s in url_names):
            return True
        if not get_keys_default(
            attrs,
            ["conda-forge.yml", "bot", "run_deps_from_wheel"],
            {},
            False,
        ):
            return True

        if "python" not in run_reqs:
            return True

        version = attrs.get("version_pr_info", {}).get("new_version", "") or attrs.get(
            "version",
            "",
        )
        wheel_url, wheel_file = self.determine_wheel(source_url, version)

        if wheel_url is None:
            return True
        return False

    def determine_wheel(self, source_url: str, version: str):
        pkg = source_url.split("/")[6]
        resp = requests.get(f"https://pypi.org/pypi/{pkg}/{version}/json")
        try:
            resp.raise_for_status()
        except Exception:
            return None, None
        wheel_count = 0
        for artifact in resp.json()["urls"]:
            if artifact["packagetype"] == "bdist_wheel":
                wheel_count += 1
                wheel_url = artifact["url"]
                wheel_file = artifact["filename"]
        if wheel_count != 1:
            return None, None
        return wheel_url, wheel_file

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        source_url = attrs.get("url") or attrs.get("source", {}).get("url")
        version = attrs.get("version_pr_info", {}).get("new_version", "") or attrs.get(
            "version",
            "",
        )
        if not version:
            return None

        wheel_url, wheel_file = self.determine_wheel(source_url, version)
        if wheel_url is None:
            return None

        # parse the versions from the wheel
        wheel_packages = {}
        with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
            resp = requests.get(wheel_url)
            with open(wheel_file, "wb") as fp:
                for chunk in resp.iter_content(chunk_size=2**16):
                    fp.write(chunk)
            import pkginfo
            import pkg_resources

            wheel_metadata = pkginfo.get_metadata(wheel_file)
            wheel_metadata.extractMetadata()
            for dep in wheel_metadata.requires_dist:
                parsed_req = pkg_resources.Requirement.parse(dep)
                # ignore extras, and markers
                # map pypi name to the conda name, with fallback to pypi name
                conda_name = pypi_conda_mapping().get(parsed_req.name, parsed_req.name)
                wheel_packages[conda_name] = str(parsed_req.specifier)

        if not wheel_packages:
            return None
        handled_packages = set()

        with pushd(recipe_dir):
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
                                + wheel_packages[pkg_name]
                                + "\n"
                            )
                            handled_packages.add(pkg_name)

                    # There are unhandled packages.  Since these might not be on
                    # conda-forge add them,
                    # but leave them commented out
                    for pkg_name in sorted(set(wheel_packages) - handled_packages):
                        # TODO: add to pr text saying that we discovered new deps
                        new_line = (
                            " " * spaces
                            + "# - "
                            + pkg_name
                            + " "
                            + wheel_packages[pkg_name]
                            + "\n"
                        )
                        handled_packages.add(pkg_name)
                        lines.insert(j, new_line)

                    break

            with open("meta.yaml", "w") as f:
                f.write("".join(lines))
