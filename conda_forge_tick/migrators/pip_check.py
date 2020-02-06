import typing

# from typing import Any

from conda_forge_tick.migrators.core import MiniMigrator

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict


class PipCheckMigrator(MiniMigrator):
    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """run pip check if we see python in any host sections"""
        host_reqs_list = (
            attrs.get("meta_yaml", {}).get("requirements", {}).get("host", [])
        )
        host_reqs = {r.split(" ")[0] for r in host_reqs_list}

        if "outputs" in attrs.get("meta_yaml", {}):
            for output in attrs.get("meta_yaml", {})["outputs"]:
                _host_reqs_list = output.get("requirements", {}).get("host", [])
                _host_reqs = {r.split(" ")[0] for r in _host_reqs_list}
                host_reqs &= _host_reqs
        return not bool(host_reqs & set("python"))

    # def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
    #     with indir(recipe_dir):
    #         for b in self.bad_install:
    #             replace_in_file(
    #                 f"script: {b}",
    #                 "script: {{ PYTHON }} -m pip install . --no-deps -vv",
    #                 "meta.yaml",
    #             )
