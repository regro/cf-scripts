import os
import re
import typing
from typing import Any

from ruamel.yaml import YAML

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.os_utils import pushd

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

SYSROOT_REGEX = re.compile(r"sysroot_linux-64\s+2\.17")
REQUIRED_RE_LINES = [
    (
        re.compile(r"^cudnn:\s+#\s+\[linux64\]\s*\n$"),
        re.compile(r"^  \s*- undefined\s+#\s+\[linux64\]\s*\n$"),
        "cudnn:                                            # [linux64]",
        "  - undefined                                     # [linux64]",
    ),
    (
        re.compile(r"^cuda_compiler_version:\s+#\s+\[linux64\]\s*\n$"),
        re.compile(r"^  \s*- None\s+#\s+\[linux64\]\s*\n$"),
        "cuda_compiler_version:                            # [linux64]",
        "  - None                                          # [linux64]",
    ),
    (
        re.compile(r"^docker_image:\s+#\s+\[linux64\]\s*\n$"),
        re.compile(
            r"^  \s*- (quay\.io\/|)condaforge\/linux-anvil-cos7-x86_64\s+#\s+\[linux64\]\s*\n$",  # noqa
        ),
        "docker_image:                                     # [linux64]",
        "  - quay.io/condaforge/linux-anvil-cos7-x86_64    # [linux64]",
    ),
    (
        re.compile(r"^cdt_name:\s+#\s+\[linux64\]\s*\n$"),
        re.compile(r"^  \s*- cos7\s+#\s+\[linux64\]\s*\n$"),
        "cdt_name:                                         # [linux64]",
        "  - cos7                                          # [linux64]",
    ),
]


def _has_line_set(cfg_lines, first_re, second_re):
    for i in range(len(cfg_lines) - 1):
        if first_re.match(cfg_lines[i]) and second_re.match(cfg_lines[i + 1]):
            return True

    return False


def _munge_cos7_lines(cfg_lines):
    for first_re, second_re, first, second in REQUIRED_RE_LINES:
        if not _has_line_set(cfg_lines, first_re, second_re):
            cfg_lines.append(first + "\n")
            cfg_lines.append(second + "\n")


class Cos7Config(MiniMigrator):
    allowed_schema_versions = {0, 1}

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        if super().filter(attrs):
            return True

        if any(
            SYSROOT_REGEX.search(line) for line in attrs["raw_meta_yaml"].splitlines()
        ):
            return False
        else:
            return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with pushd(recipe_dir):
            cfg = "conda_build_config.yaml"

            yaml = YAML()
            yaml.indent(mapping=2, sequence=4, offset=2)
            if os.path.exists("../conda-forge.yml"):
                with open("../conda-forge.yml") as fp:
                    cfyml = yaml.load(fp.read())
            else:
                cfyml = {}

            if (
                os.path.exists(cfg)
                and cfyml.get("os_version", {}).get("linux_64", None) != "cos7"
            ):
                with open(cfg) as fp:
                    lines = fp.readlines()

                _munge_cos7_lines(lines)

                with open(cfg, "w") as fp:
                    fp.write("".join(lines))
