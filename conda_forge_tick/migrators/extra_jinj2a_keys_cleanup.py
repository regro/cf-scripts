import os
import re
import typing
import logging
from typing import Any

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.os_utils import pushd

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)

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
            rf"{{% set {key_name} = [\'\"]?(?P<var_value>.+?)[\'\"]? %}}",
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
        with pushd(recipe_dir):
            if not os.path.exists("meta.yaml") and os.path.exists("recipe.yaml"):
                logger.info(f"Skipping {self.__class__.__name__} for recipe.yaml")
                return
            with open("meta.yaml") as fp:
                lines = fp.readlines()

            for var_name in self.vars_to_remove:
                lines = self._replace_jinja_key(var_name, lines)

            # Rewrite the recipe file
            with open("meta.yaml", "w") as fp:
                fp.writelines(lines)
