import os
import typing
from typing import Any
from ruamel.yaml import YAML

from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.migrators.core import MiniMigrator

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict


class MaxVerMigrator(MiniMigrator):
    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """only remove the keys if they are there"""
        if (
            'max_r_ver' in attrs.get("conda-forge.yml") or
            'max_py_ver' in attrs.get("conda-forge.yml")
        ):
            return False
        else:
            return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            cfg_path = os.path.join('..', 'conda-forge.yml')
            yaml = YAML()
            yaml.indent(mapping=2, sequence=4, offset=2)

            with open(cfg_path, 'r') as fp:
                cfg = yaml.load(fp.read())

            if 'max_r_ver' in cfg:
                del cfg['max_r_ver']
            if 'max_py_ver' in cfg:
                del cfg['max_py_ver']

            with open(cfg_path, 'w') as fp:
                yaml.dump(cfg, fp)
