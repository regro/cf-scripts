import re
import typing
from typing import Any

from conda_forge_tick.migrators.core import MiniMigrator, skip_migrator_due_to_schema
from conda_forge_tick.os_utils import pushd

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict


def _cleanup_raw_yaml(raw_yaml):
    lines = []
    for line in raw_yaml.splitlines():
        line = line.replace("{{ native }}", "")
        line = line.replace("{{native}}", "")
        line = line.replace("{{posix}}pkg-config", "pkg-config")
        line = line.replace("{{ posix }}pkg-config", "pkg-config")
        line = line.replace("- m2w64-pkg-config", "- pkg-config")
        line = line.replace("- m2w64-toolchain", "- {{ compiler('m2w64_c') }}")
        line = line.replace("- posix", "- m2-base")
        if "merge_build_host: " in line:
            continue
        if "- gcc-libs" in line:
            continue
        if "set native =" in line:
            continue
        if re.search(r"\s*skip: (T|t)rue\s+\# \[win\]", line):
            nspaces = len(line) - len(line.lstrip())
            spaces = " " * nspaces
            comment = (
                spaces
                + "# Checking windows to see if it passes. Uncomment the line if it fails."
            )
            lines.append(comment)
            lines.append(spaces + "# " + line.lstrip())
            continue
        lines.append(line)

    return "\n".join(lines) + "\n"


class RUCRTCleanup(MiniMigrator):
    """Cleanup the R recipes for ucrt."""

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        return (
            not any(
                w in attrs.get("raw_meta_yaml", "")
                for w in ["native", "- posix", "- m2w64"]
            )
        ) or skip_migrator_due_to_schema(attrs, self.allowed_schema_versions)

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with pushd(recipe_dir):
            with open("meta.yaml") as fp:
                raw_yaml = fp.read()

            raw_yaml = _cleanup_raw_yaml(raw_yaml)

            # Rewrite the recipe file
            with open("meta.yaml", "w") as fp:
                fp.write(raw_yaml)
