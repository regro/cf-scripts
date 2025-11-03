import copy
import os
import typing
from typing import Any, Literal

from conda_forge_tick.migrators.core import _parse_bad_attr, skip_migrator_due_to_schema
from conda_forge_tick.migrators.replacement import Replacement
from conda_forge_tick.utils import frozen_to_json_friendly

from ..migrators_types import (
    AttrsTypedDict,
    MigrationUidTypedDict,
    RequirementsTypedDict,
)


class MatplotlibBase(Replacement):
    migrator_version = 0

    def filter(self, attrs: AttrsTypedDict, not_bad_str_start: str = "") -> bool:
        # I shipped a bug where I added an entry to the migrator uid and now the
        # graph is corrupted - this is being fixed here
        def parse_already_pred() -> bool:
            migrator_uid: "MigrationUidTypedDict" = typing.cast(
                "MigrationUidTypedDict",
                frozen_to_json_friendly(self.migrator_uid(attrs))["data"],
            )
            already_migrated_uids: typing.Iterable["MigrationUidTypedDict"] = list(
                copy.deepcopy(z["data"])
                for z in attrs.get("pr_info", {}).get("PRed", [])  # type: ignore
            )

            # we shipped a bug, so fixing this here -
            # need to ignore name in uuid
            for uid in already_migrated_uids:
                if uid["migrator_name"] == "MatplotlibBase" and "name" in uid:
                    del uid["name"]
            del migrator_uid["name"]

            return migrator_uid in already_migrated_uids

        _is_archived = attrs.get("archived", False)
        _is_pred = parse_already_pred()
        _is_bad = _parse_bad_attr(attrs, not_bad_str_start)

        requirements: RequirementsTypedDict = attrs.get("requirements", {})
        rq = (
            requirements.get("build", set())
            | requirements.get("host", set())
            | requirements.get("run", set())
            | requirements.get("test", set())
        )
        _no_dep = len(rq & self.packages) == 0

        return (
            _is_archived
            or _is_pred
            or _is_bad
            or _no_dep
            or skip_migrator_due_to_schema(attrs, self.allowed_schema_versions)
        )

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> MigrationUidTypedDict | Literal[False]:
        yum_pth = os.path.join(recipe_dir, "yum_requirements.txt")
        if not os.path.exists(yum_pth):
            yum_lines = []
        else:
            with open(yum_pth) as fp:
                yum_lines = fp.readlines()

        if "xorg-x11-server-Xorg\n" not in yum_lines:
            yum_lines.append("xorg-x11-server-Xorg\n")

        for i in range(len(yum_lines)):
            if yum_lines[i][-1] != "\n":
                yum_lines[i] = yum_lines[i] + "\n"

        with open(yum_pth, "w") as fp:
            for line in yum_lines:
                fp.write(line)

        return super().migrate(recipe_dir, attrs, **kwargs)
