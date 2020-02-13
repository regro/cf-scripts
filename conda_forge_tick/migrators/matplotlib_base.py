import os
import typing
from typing import Any

from conda_forge_tick.migrators.core import Replacement
if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict, MigrationUidTypedDict


class MatplotlibBase(Replacement):
    migrator_version = 0

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":

        yum_pth = os.path.join(recipe_dir, 'yum_requirements.txt')
        if not os.path.exists(yum_pth):
            yum_lines = []
        else:
            with open(yum_pth, 'r') as fp:
                yum_lines = fp.readlines()

        if 'xorg-x11-server-Xorg\n' not in yum_lines:
            yum_lines.append('xorg-x11-server-Xorg\n')
            
        for i in range(len(yum_lines)):
            if yum_lines[i][-1] != '\n':
                yum_lines[i] = yum_lines[i] + '\n'

        with open(yum_pth, 'w') as fp:
            for line in yum_lines:
                fp.write(line)

        return super().migrate(recipe_dir, attrs, **kwargs)
