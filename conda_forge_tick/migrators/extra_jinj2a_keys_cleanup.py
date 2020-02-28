import os
import typing
from typing import Any
from ruamel.yaml import YAML

from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.recipe_parser import CondaMetaYAML

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
        'file_ext',
        'hash_type',
        'hash_value',
    )

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """Check the raw YAML to find jinja variables to deal with."""
        raw_yaml = attrs['raw_meta_yaml']
        for var_name in self.vars_to_remove:
            if f'{{% set {var_name}' in raw_yaml:
                return False
        return True

    def _replace_jinja_key(self, key_name, lines):
        """Replace any usage of and the definition of a jinja2 variable."""
        key_val = None
        var_use = "{{ " + key_name + " }}"
        var_def = "{% set " + key_name
        for line in lines:
            if line.startswith(var_def):
                quote1_idx = line.find('"')
                quote2_idx = line.rfind('"')
                key_val = line[quote1_idx+1:quote2_idx]
                continue
            if key_val is not None:
                # in a string literal
                line = line.replace("'" + var_use + "'", key_val)
                line = line.replace(var_use, key_val)
            yield line

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            with open('meta.yaml', 'r') as fp:
                lines = fp.readlines()

            for var_name in self.vars_to_remove:
                lines = list(self._replace_jinja_key(var_name, lines))

            # Rewrite the recipe file
            with open('meta.yaml', 'w') as fp:
                fp.writelines(lines)
