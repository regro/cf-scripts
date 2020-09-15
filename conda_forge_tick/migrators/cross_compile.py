import os
import re
import tempfile
import subprocess
import typing
from typing import Any
import logging

from rever.tools import replace_in_file

from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.utils import eval_cmd, _get_source_code
from conda_forge_tick.recipe_parser import CondaMetaYAML
from conda_forge_tick.migrators.core import MiniMigrator

LOGGER = logging.getLogger("conda_forge_tick.migrators.cross_compile")


class CrossCompilationMigratorBase(MiniMigrator):
    post_migration = True

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        build_reqs = attrs.get("requirements", {}).get("build", set())
        needed = False
        for compiler in [
            "fortran_compiler_stub",
            "c_compiler_stub",
            "cxx_compiler_stub",
        ]:
            if compiler in build_reqs:
                needed = True
                break
        return not needed


class UpdateConfigSubGuessMigrator(CrossCompilationMigratorBase):
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
                for line in lines:
                    if line.strip().startswith(
                        "cp $BUILD_PREFIX/share/libtool/build-aux/config",
                    ):
                        return
                    if line.strip().startswith("autoreconf"):
                        return
                    if line.strip().startswith("./autogen.sh"):
                        return
                insert_at = 0
                if lines[0].startswith("#"):
                    insert_at = 1
                for d in directories:
                    lines.insert(
                        insert_at,
                        f"cp $BUILD_PREFIX/share/libtool/build-aux/config.* {d}\n",
                    )
                lines.insert(
                    insert_at, "# Get an updated config.sub and config.guess\n",
                )
            with open("build.sh", "w") as f:
                f.write("".join(lines))

            with open("meta.yaml") as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if line.strip().startswith("- {{ compiler"):
                    new_line = " " * (len(line) - len(line.lstrip()))
                    new_line += "- libtool  # [unix]\n"
                    lines.insert(i, new_line)
                    break

            with open("meta.yaml", "w") as f:
                f.write("".join(lines))


class GuardTestingMigrator(CrossCompilationMigratorBase):
    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            if not os.path.exists("build.sh"):
                return
            with open("build.sh", "r") as f:
                lines = list(f.readlines())

            for i, line in enumerate(lines):
                if "CONDA_BUILD_CROSS_COMPILATION" in line:
                    return
                if (
                    line.startswith("make check")
                    or line.startswith("ctest")
                    or line.startswith("make test")
                ):
                    lines.insert(
                        i, 'if [[ "${CONDA_BUILD_CROSS_COMPILATION}" != "1" ]]; then\n',
                    )
                    insert_after = i + 1
                    while len(lines) > insert_after and lines[insert_after].endswith(
                        "\\\n",
                    ):
                        insert_after += 1
                    if lines[insert_after][-1] != "\n":
                        lines[insert_after] += "\n"
                    lines.insert(insert_after + 1, "fi\n")
                    break
            else:
                return
            with open("build.sh", "w") as f:
                f.write("".join(lines))


class CrossPythonMigrator(CrossCompilationMigratorBase):
    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        host_reqs = attrs.get("requirements", {}).get("host", set())
        return "python" not in host_reqs or "python" in build_reqs

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        host_reqs = attrs.get("requirements", {}).get("host", set())
        with indir(recipe_dir):
            if not os.path.exists("build.sh"):
                return
            with open("meta.yaml") as f:
                lines = f.readlines()
            in_reqs = False
            for i, line in enumerate(lines):
                if line.strip().startswith("requirements"):
                    in_reqs = True
                if in_reqs and len(line) > 0 and line[0] != " ":
                    in_reqs = False
                if not in_reqs:
                    continue
                if line.strip().startswith("build:"):
                    j = i + 1
                    while j < len(lines) and not line[i].strip().startswith("-"):
                        j = j + 1
                    if j == len(lines):
                        j = i + 1
                        spaces = len(line) - len(line.lstrip()) + 2
                    else:
                        spaces = len(lines[j]) - len(lines[j].lstrip())
                    new_line = " " * spaces
                    for pkg in reversed(
                        ["python", "cross-python", "cython", "numpy", "pybind11"],
                    ):
                        if pkg in host_reqs or pkg == "cross-python":
                            new_line = (
                                " " * spaces
                                + "- "
                                + pkg.ljust(15)
                                + "  # [build_platform != target_platform]\n"
                            )
                            lines.insert(i, new_line)
                    break

            with open("meta.yaml", "w") as f:
                f.write("".join(lines))


class UpdateCMakeArgsMigrator(CrossCompilationMigratorBase):
    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        build_reqs = attrs.get("requirements", {}).get("build", set())
        return "cmake" not in build_reqs

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            if not os.path.exists("build.sh"):
                return
            with open("build.sh", "r") as f:
                lines = list(f.readlines())

            for i, line in enumerate(lines):
                if line.startswith("cmake "):
                    lines[i] = "cmake ${CMAKE_ARGS} " + line[len("cmake ") :]
                    break
            else:
                return

            with open("build.sh", "w") as f:
                f.write("".join(lines))
