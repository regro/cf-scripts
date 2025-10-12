import os
from typing import Any

from conda_smithy.utils import get_yaml as smithy_get_yaml
from ruamel.yaml import YAML

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.os_utils import pushd

from ..migrators_types import AttrsTypedDict


class CondaForgeYAMLCleanup(MiniMigrator):
    allowed_schema_versions = {0, 1}
    keys_to_remove = [
        "min_r_ver",
        "max_r_ver",
        "min_py_ver",
        "max_py_ver",
        "compiler_stack",
    ]
    keys_to_change = [
        "test_on_native_only",
        "abi_migration_branches",
    ]

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """Remove recipes without a conda-forge.yml file that has the keys to remove or change."""
        if super().filter(attrs):
            return True

        cfy = attrs.get("conda-forge.yml", {})
        if any(key in cfy for key in (self.keys_to_remove + self.keys_to_change)):
            return False
        else:
            return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with pushd(recipe_dir):
            cfg_path = os.path.join("..", "conda-forge.yml")

            # we first "round trip" the file through smithy's yaml reader
            # this takes care of duplicate line errors in that it handles them
            # just like smithy does
            smithy_yaml = smithy_get_yaml(allow_duplicate_keys=True)
            with open(cfg_path) as fp:
                cfg = smithy_yaml.load(fp.read())
            with open(cfg_path, "w") as fp:
                smithy_yaml.dump(cfg, fp)

            # now we use our own yaml parser to help with formatting
            # of spaces, indents, etc.
            yaml = YAML()
            yaml.indent(mapping=2, sequence=4, offset=2)

            with open(cfg_path) as fp:
                cfg = yaml.load(fp.read())

            for k in self.keys_to_remove:
                if k in cfg:
                    del cfg[k]

            if "test_on_native_only" in cfg:
                value = cfg["test_on_native_only"]
                del cfg["test_on_native_only"]
                if value:
                    cfg["test"] = "native_and_emulated"

            if "abi_migration_branches" in cfg:
                cfg["abi_migration_branches"] = [
                    str(v) for v in cfg["abi_migration_branches"]
                ]

            with open(cfg_path, "w") as fp:
                yaml.dump(cfg, fp)
