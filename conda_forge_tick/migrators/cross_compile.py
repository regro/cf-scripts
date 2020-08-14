import os
import re
import tempfile
import subprocess
import typing
from typing import Any
import logging

from rever.tools import replace_in_file

from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.utils import eval_cmd
from conda_forge_tick.recipe_parser import CondaMetaYAML
from conda_forge_tick.migrators.core import (
    MiniMigrator,
    _get_source_code,
)

LOGGER = logging.getLogger("conda_forge_tick.migrators.cross_compile")


class UpdateConfigSubGuessMigrator(MiniMigrator):
    post_migration = True

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        build_reqs = attrs.get("requirements"{}).get("build", set())
        needed = False
        for compiler in ["fortran_compiler_stub", "c_compiler_stub", "cxx_compiler_stub"]:
            if compiler in build_reqs:
                needed = True
                break
        return not needed

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        cb_work_dir = _get_source_code(recipe_dir)
        if cb_work_dir is None:
            return
        directories = set()
        with indir(cb_work_dir):
            for dp, dn, fn in os.walk("."):
                for f in fn:
                    if f != "config.sub":
                        continue
                    if os.path.exists(os.path.join(dp, "config.guess")):
                        directories.add(dp)

        if not directories:
            return

        with indir(recipe_dir):
            if not os.path.exists("build.sh"):
                return
            with open("build.sh", "r") as f:
                lines = list(f.readlines())
                insert_at = 0
                if lines[0].startswith("#"):
                    insert_at = 1
                for d in directories:
                    lines.insert(insert_at, f"cp $BUILD_PREFIX/share/libtool/build-aux/config.* {d}")
                lines.insert(insert_at, "# Get an updated config.sub and config.guess")
            with open("build.sh", "w") as f:
                f.write(lines)

            with open("meta.yaml") as f:
                lines = f.splitlines()
            for i, line in enumerate(lines):
                if line.strip().startswith("- {{ compiler"):
                    new_line = " "*(len(line)-len(line.lstrip()))
                    new_line += "- libtool  # [unix]"
                    lines.insert(i, new_line)
                    break

            with open("meta.yaml", "w") as f:
                f.write(lines)
