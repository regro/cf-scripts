import re
import typing
from typing import Any

from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.migrators.core import MiniMigrator

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

JINJA2_VAR_RE = re.compile(r"{{\s*(.*?)\s*}}")


def _should_filter(raw_yaml):
    for line in raw_yaml.splitlines():
        if JINJA2_VAR_RE.search(line):
            return False

    return True


def _cleanup_raw_yaml(raw_yaml):
    def _cleanup(m):
        return "{{ %s }}" % (m.group(1).strip())

    lines = []
    for line in raw_yaml.splitlines():
        lines.append(JINJA2_VAR_RE.sub(_cleanup, line))

    return "\n".join(lines) + "\n"


class Jinja2VarsCleanup(MiniMigrator):
    """Cleanup the jinja2 vars by replacing {{name}} with {{ name }} etc."""

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        return _should_filter(attrs.get("raw_meta_yaml", ""))

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            with open("meta.yaml", "r") as fp:
                raw_yaml = fp.read()

            raw_yaml = _cleanup_raw_yaml(raw_yaml)

            # Rewrite the recipe file
            with open("meta.yaml", "w") as fp:
                fp.write(raw_yaml)
