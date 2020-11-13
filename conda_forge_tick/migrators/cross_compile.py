import os
import typing
from typing import Any
import logging

from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.utils import _get_source_code
from conda_forge_tick.migrators.core import MiniMigrator

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

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
        if attrs["feedstock_name"] == "libtool" || attrs["feedstock_name"] == "gnuconfig":
            return
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
            with open("build.sh") as f:
                lines = list(f.readlines())
                for line in lines:
                    if line.strip().startswith(
                        "cp $BUILD_PREFIX/share/gnuconfig",
                    ):
                        return
                    if line.strip().startswith(
                        "cp $BUILD_PREFIX/share/libtool/build-aux/config",
                    ):
                        return
                    if line.strip().startswith("autoreconf"):
                        for word in line.split(" "):
                            if word == "--force":
                                return
                            if word.startwith("-") and not word.startwith("--") and "f" in word:
                                return
                    if line.strip().startswith("./autogen.sh"):
                        return
                insert_at = 0
                if lines[0].startswith("#"):
                    insert_at = 1
                for d in directories:
                    lines.insert(
                        insert_at,
                        f"cp $BUILD_PREFIX/share/gnuconfig/config.* {d}\n",
                    )
                lines.insert(
                    insert_at,
                    "# Get an updated config.sub and config.guess\n",
                )
            with open("build.sh", "w") as f:
                f.write("".join(lines))

            with open("meta.yaml") as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if line.strip().startswith("- {{ compiler"):
                    new_line = " " * (len(line) - len(line.lstrip()))
                    new_line += "- gnuconfig  # [unix]\n"
                    lines.insert(i, new_line)
                    break

            with open("meta.yaml", "w") as f:
                f.write("".join(lines))


class GuardTestingMigrator(CrossCompilationMigratorBase):
    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            if not os.path.exists("build.sh"):
                return
            with open("build.sh") as f:
                lines = list(f.readlines())

            for i, line in enumerate(lines):
                if "CONDA_BUILD_CROSS_COMPILATION" in line:
                    return
                if (
                    line.strip().startswith("make check")
                    or line.strip().startswith("ctest")
                    or line.strip().startswith("make test")
                ):
                    lines.insert(
                        i,
                        'if [[ "${CONDA_BUILD_CROSS_COMPILATION}" != "1" ]]; then\n',
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
        build_reqs = attrs.get("requirements", {}).get("build", set())
        return "python" not in host_reqs or "python" in build_reqs

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        host_reqs = attrs.get("requirements", {}).get("host", set())
        with indir(recipe_dir):
            with open("meta.yaml") as f:
                lines = f.readlines()
            in_reqs = False
            for i, line in enumerate(lines):
                if line.strip().startswith("requirements:"):
                    in_reqs = True
                    continue
                if in_reqs and len(line) > 0 and line[0] != " ":
                    in_reqs = False
                if not in_reqs:
                    continue
                if line.strip().startswith("build:") or line.strip().startswith(
                    "host:",
                ):
                    j = i + 1
                    while j < len(lines) and not lines[j].strip().startswith("-"):
                        j = j + 1
                    if j == len(lines):
                        j = i + 1
                        spaces = len(line) - len(line.lstrip()) + 2
                    else:
                        spaces = len(lines[j]) - len(lines[j].lstrip())
                    new_line = " " * spaces
                    if line.strip().startswith("host:"):
                        lines.insert(i, line.replace("host", "build"))
                    for pkg in reversed(
                        [
                            "python",
                            "cross-python_{{ target_platform }}",
                            "cython",
                            "numpy",
                            "cffi",
                            "pybind11",
                        ],
                    ):
                        if pkg in host_reqs or pkg.startswith("cross-python"):
                            new_line = (
                                " " * spaces
                                + "- "
                                + pkg.ljust(37)
                                + "  # [build_platform != target_platform]\n"
                            )
                            lines.insert(i + 1, new_line)
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
            with open("build.sh") as f:
                lines = list(f.readlines())

            for i, line in enumerate(lines):
                if "${CMAKE_ARGS}" in line or "$CMAKE_ARGS" in line:
                    return

            for i, line in enumerate(lines):
                if line.startswith("cmake "):
                    lines[i] = "cmake ${CMAKE_ARGS} " + line[len("cmake ") :]
                    break
            else:
                return

            with open("build.sh", "w") as f:
                f.write("".join(lines))


class Build2HostMigrator(MiniMigrator):
    post_migration = False

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        build_reqs = attrs.get("requirements", {}).get("build", set())
        host_reqs = attrs.get("requirements", {}).get("host", set())
        run_reqs = attrs.get("requirements", {}).get("run", set())
        if (
            len(attrs.get("outputs_names", [])) <= 1
            and "python" in build_reqs
            and "python" in run_reqs
            and not host_reqs
            and "host" not in attrs.get("meta_yaml", {}).get("requirements", {})
            and not any(
                c in build_reqs
                for c in [
                    "fortran_compiler_stub",
                    "c_compiler_stub",
                    "cxx_compiler_stub",
                ]
            )
        ):
            return False
        else:
            return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            with open("meta.yaml") as fp:
                meta_yaml = fp.readlines()

            new_lines = []
            in_req = False
            for line in meta_yaml:
                if "requirements:" in line:
                    in_req = True
                if in_req and line.strip().startswith("build:"):
                    start, rest = line.split("build:", 1)
                    line = start + "host:" + rest
                    in_req = False
                new_lines.append(line)

            with open("meta.yaml", "w") as f:
                f.write("".join(new_lines))


class NoCondaInspectMigrator(MiniMigrator):
    post_migration = True

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        if "conda inspect" in attrs.get("raw_meta_yaml", ""):
            return False
        else:
            return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            with open("meta.yaml") as fp:
                meta_yaml = fp.readlines()

            new_lines = []
            for line in meta_yaml:
                if "conda inspect" in line:
                    continue
                new_lines.append(line)

            with open("meta.yaml", "w") as f:
                f.write("".join(new_lines))
