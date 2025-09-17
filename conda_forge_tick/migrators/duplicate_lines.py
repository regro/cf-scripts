import re
import typing
from typing import Any

from conda_forge_tick.migrators.core import MiniMigrator, skip_migrator_due_to_schema
from conda_forge_tick.os_utils import pushd

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict


class DuplicateLinesCleanup(MiniMigrator):
    # duplicate keys are an error in v1 recipes
    allowed_schema_versions = {0}
    regex_to_check = {
        "noarch: generic": re.compile(r"^\s*noarch:\s*generic\s*$"),
        "noarch: python": re.compile(r"^\s*noarch:\s*python\s*$"),
    }

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        if super().filter(attrs):
            return True
        # we are not handling outputs here since they can make things confusing
        if "outputs" in attrs.get("meta_yaml", ""):
            return True

        raw_yaml = attrs.get("raw_meta_yaml", "")
        for line in raw_yaml.splitlines():
            if any(r.match(line) for r in self.regex_to_check.values()):
                return False or skip_migrator_due_to_schema(
                    attrs, self.allowed_schema_versions
                )

        return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with pushd(recipe_dir):
            with open("meta.yaml") as fp:
                raw_yaml = fp.read()

            new_lines = []
            matched = {k: 0 for k in self.regex_to_check}
            for line in raw_yaml.splitlines():
                keep = True
                for k, v in self.regex_to_check.items():
                    if v.match(line):
                        matched[k] += 1
                        if matched[k] > 1:
                            keep = False

                if keep:
                    new_lines.append(line)

            new_yaml = "\n".join(new_lines) + "\n"

            with open("meta.yaml", "w") as fp:
                fp.write(new_yaml)
