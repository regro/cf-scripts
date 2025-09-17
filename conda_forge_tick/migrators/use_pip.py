import typing
from typing import Any

from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import as_iterable

from .core import MiniMigrator, skip_migrator_due_to_schema

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict


class PipMigrator(MiniMigrator):
    bad_install = (
        "python setup.py install",
        "python -m pip install --no-deps --ignore-installed .",
    )

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        scripts = as_iterable(
            attrs.get("meta_yaml", {}).get("build", {}).get("script", []),
        )
        return (
            not bool(set(self.bad_install) & set(scripts))
        ) or skip_migrator_due_to_schema(attrs, self.allowed_schema_versions)

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with pushd(recipe_dir):
            with open("meta.yaml") as fp:
                lines = fp.readlines()

            new_lines = []
            for line in lines:
                for b in self.bad_install:
                    tst_str = "script: %s" % b
                    if tst_str in line:
                        line = line.replace(
                            tst_str,
                            "script: {{ PYTHON }} -m pip install . --no-deps -vv",
                        )
                        break
                new_lines.append(line)

            with open("meta.yaml", "w") as fp:
                for line in new_lines:
                    fp.write(line)
