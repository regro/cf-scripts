import re
import typing
from typing import Any

from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.migrators.core import MiniMigrator

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict


class ExtraJinja2KeysCleanup(MiniMigrator):
    """Remove extra Jinja2 keys that make things hard for the version migrator.

    Variables removed:

    - ``hash_type``: This is sometimes used as a key in the ``source`` section
      to map the hash_type (ex. sha256) to the hash.
    - ``hash_value``: This is unnecessary since it is typically only used once
      in a YAML recipe.
    - ``file_ext``: This is unnecessary and just makes things harder to read.
      It may also be causing trouble for the version migrator.

    """

    vars_to_remove = (
        "file_ext",
        "hash_type",
        "hash_value",
    )

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """Check the raw YAML to find jinja variables to deal with."""
        raw_yaml = attrs["raw_meta_yaml"]
        for var_name in self.vars_to_remove:
            if f"{{% set {var_name}" in raw_yaml:
                return False
        return True

    def _replace_jinja_key(self, key_name, lines):
        """Replace any usage of and the definition of a jinja2 variable."""
        var_def_regex = re.compile(
            fr"{{% set {key_name} = [\'\"]?(?P<var_value>.+?)[\'\"]? %}}",
        )
        var_use = "{{ " + key_name + " }}"
        var_value = None
        for line in lines:
            if var_value is None:
                match = var_def_regex.match(line)
                if match is not None:
                    var_value = match.groupdict()["var_value"]
                    # we found this variable definition
                    # don't include it in the output
                    continue
            if var_value is not None:
                line = line.replace(var_use, var_value)
            yield line

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            with open("meta.yaml", "r") as fp:
                lines = fp.readlines()

            for var_name in self.vars_to_remove:
                lines = self._replace_jinja_key(var_name, lines)

            # Rewrite the recipe file
            with open("meta.yaml", "w") as fp:
                fp.writelines(lines)
