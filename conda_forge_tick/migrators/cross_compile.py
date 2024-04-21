import logging
import os
import typing
from typing import Any

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.provide_source_code import provide_source_code
from conda_forge_tick.utils import yaml_safe_dump, yaml_safe_load

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)


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
        if (
            attrs["feedstock_name"] == "libtool"
            or attrs["feedstock_name"] == "gnuconfig"
        ):
            return
        try:
            with provide_source_code(recipe_dir) as cb_work_dir:
                if cb_work_dir is None:
                    return
                directories = set()
                with pushd(cb_work_dir):
                    for dp, dn, fn in os.walk("."):
                        for f in fn:
                            if f != "config.sub":
                                continue
                            if os.path.exists(os.path.join(dp, "config.guess")):
                                directories.add(dp)

                if not directories:
                    return

                with pushd(recipe_dir):
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
                                    if (
                                        word.startswith("-")
                                        and not word.startswith("--")
                                        and "f" in word
                                    ):
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
        except RuntimeError:
            return


class GuardTestingMigrator(CrossCompilationMigratorBase):
    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with pushd(recipe_dir):
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
                        'if [[ "${CONDA_BUILD_CROSS_COMPILATION:-}" != "1" '
                        '|| "${CROSSCOMPILING_EMULATOR}" != "" ]]; then\n',
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
        with pushd(recipe_dir):
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
        with pushd(recipe_dir):
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
        with pushd(recipe_dir):
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
        with pushd(recipe_dir):
            with open("meta.yaml") as fp:
                meta_yaml = fp.readlines()

            new_lines = []
            for line in meta_yaml:
                if "conda inspect" in line:
                    continue
                new_lines.append(line)

            with open("meta.yaml", "w") as f:
                f.write("".join(new_lines))


CRAN_BUILD_SH = """\
#!/bin/bash

export DISABLE_AUTOBREW=1

# shellcheck disable=SC2086
${R} CMD INSTALL --build . ${R_ARGS}
"""


class CrossRBaseMigrator(CrossCompilationMigratorBase):
    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        host_reqs = attrs.get("requirements", {}).get("host", set())
        if "r-base" in host_reqs or attrs.get("name", "").startswith("r-"):
            return False
        else:
            return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with pushd(recipe_dir):
            with open("meta.yaml") as fp:
                meta_yaml = fp.readlines()

            new_lines = []
            in_req = False
            previous_was_build = False
            for line in meta_yaml:
                if previous_was_build:
                    nspaces = len(line) - len(line.lstrip())
                    new_lines.append(
                        " " * nspaces
                        + "- cross-r-base {{ r_base }}  # [build_platform != target_platform]\n",
                    )
                    # Add host R requirements to build
                    host_reqs = attrs.get("requirements", {}).get("host", set())
                    r_host_reqs = [
                        req
                        for req in host_reqs
                        if req.startswith("r-") and req != "r-base"
                    ]
                    for r_req in r_host_reqs:
                        # Ensure nice formatting
                        post_nspaces = max(0, 25 - len(r_req))
                        new_lines.append(
                            " " * nspaces
                            + "- "
                            + r_req
                            + " " * post_nspaces
                            + "  # [build_platform != target_platform]\n",
                        )
                    in_req = False
                    previous_was_build = False
                if "requirements:" in line:
                    in_req = True
                if in_req and line.strip().startswith("build:"):
                    previous_was_build = True
                new_lines.append(line)

            with open("meta.yaml", "w") as f:
                f.write("".join(new_lines))

            if os.path.exists("build.sh"):
                with open("build.sh", "w") as f:
                    f.write(CRAN_BUILD_SH)


class CrossCompilationForARMAndPower(MiniMigrator):
    post_migration = True

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        return False

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with pushd(recipe_dir):
            if not os.path.exists("../conda-forge.yml"):
                name = attrs.get("feedstock_name")
                logger.info(f"no conda-forge.yml for {name}")
                return

            with open("../conda-forge.yml") as f:
                config = yaml_safe_load(f)

            build_platform = config.get("build_platform", {})
            if build_platform:
                for arch in ["linux_aarch64", "linux_ppc64le"]:
                    if arch in build_platform:
                        continue
                    if config.get("provider", {}).get(arch) == "default":
                        config["build_platform"][arch] = "linux_64"
                with open("../conda-forge.yml", "w") as f:
                    name = attrs.get("feedstock_name")
                    logger.info(f"new conda-forge.yml for {name}:={config}")
                    yaml_safe_dump(config, f)

            if not os.path.exists("build.sh"):
                return
            with open("build.sh") as f:
                lines = list(f.readlines())

            old_guard_lines = [
                'if [[ "${CONDA_BUILD_CROSS_COMPILATION:-}" != "1" ]]; then\n',
                'if [[ "${CONDA_BUILD_CROSS_COMPILATION}" != "1" ]]; then\n',
                'if [[ "$CONDA_BUILD_CROSS_COMPILATION" != "1" ]]; then\n',
                'if [[ "$CONDA_BUILD_CROSS_COMPILATION" == "0" ]]; then\n',
                'if [[ "${CONDA_BUILD_CROSS_COMPILATION}" == "0" ]]; then\n',
            ]
            new_guard_line = (
                'if [[ "${CONDA_BUILD_CROSS_COMPILATION:-}" != "1" '
                '|| "${CROSSCOMPILING_EMULATOR}" != "" ]]; then\n'
            )
            for i, line in enumerate(lines):
                if (
                    (
                        line.strip().startswith("make check")
                        or line.strip().startswith("ctest")
                        or line.strip().startswith("make test")
                    )
                    and i > 0
                    and lines[i - 1] in old_guard_lines
                ):
                    lines[i - 1] = new_guard_line
                    break
            else:
                return
            with open("build.sh", "w") as f:
                f.write("".join(lines))
