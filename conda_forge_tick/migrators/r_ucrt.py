import typing
from typing import Any

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.os_utils import pushd

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict


def _cleanup_raw_yaml(raw_yaml):
    lines = []
    for line in raw_yaml.splitlines():
        line = line.replace("{{ native }}", "")
        line = line.replace("{{native}}", "")
        if "merge_build_host: " in line:
            continue
        if "- gcc-libs" in line:
            continue
        if "- posix" in line:
            continue
        if "set native =" in line:
            continue
        lines.append(line)

    return "\n".join(lines) + "\n"


class RUCRTCleanup(MiniMigrator):
    """Cleanup the R recipes for ucrt"""

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        return "native" not in attrs.get("raw_meta_yaml", "")

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with pushd(recipe_dir):
            with open("meta.yaml") as fp:
                raw_yaml = fp.read()

            raw_yaml = _cleanup_raw_yaml(raw_yaml)

            # Rewrite the recipe file
            with open("meta.yaml", "w") as fp:
                fp.write(raw_yaml)
