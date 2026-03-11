import re
import textwrap
from typing import Any

from conda_forge_tick.contexts import ClonedFeedstockContext
from conda_forge_tick.migrators.core import Migrator
from conda_forge_tick.migrators_types import AttrsTypedDict, MigrationUidTypedDict
from conda_forge_tick.os_utils import pushd

cdt_mapping = {
    "libx11-devel": "xorg-libx11",
    "libxext-devel": "xorg-libxext",
    "libxrender-devel": "xorg-libxrender",
    "libdrm-devel": "libdrm",
    "libxcomposite-devel": "xorg-libxcomposite",
    "libxcursor-devel": "xorg-libxcursor",
    "libxdamage": "xorg-libxdamage",
    "libxfixes": "xorg-libxfixes",
    "libxscrnsaver-devel": "xorg-libxscrnsaver",
    "libxtst-devel": "xorg-libxtst",
    "libxxf86vm": "xorg-libxxf86vm",
    "libselinux-devel": "libselinux-devel",
    "xorg-x11-proto-devel": "xorgproto",
    "libxrender": "xorg-libxrender",
    "libxext": "xorg-libxext",
    "libsm-devel": "xorg-libsm",
    "mesa-libgbm": "libgl-devel",
    "mesa-libgl-devel": "libgl-devel",
    "mesa-dri-drivers": "libgl-devel",
    "mesa-libegl-devel": "libgl-devel",
    "libselinux": "libselinux",
    "libglvnd-opengl": "libglvnd-opengl",
    "systemd-devel": "systemd-devel",
    "libudev-devel": "libudev-devel",
    "numactl-devel": "numactl-devel",
    "pciutils-devel": "pciutils-devel",
    "libxi-devel": "xorg-libxi",
    "libxrandr-devel": "xorg-librandr",
    "alsa-lib-devel": "alsa-lib-devel",
    "gtk2-devel": "gtk2-devel",
}


def _replace_cdts(yaml):

    def replacer(match):
        print(match)
        package = match.group(1).strip()
        return cdt_mapping[package]

    pattern = re.compile(
        r"\{\{ \s* cdt\( ['\"] (?P<cdt> .+?) ['\"] \) \s* \}\}"
        r"(?P<post_package> .*?) (?P<selector> \#.*)? $",
        re.VERBOSE | re.MULTILINE,
    )
    replaced_yaml = pattern.sub(replacer, yaml)
    return replaced_yaml


class CDTMigrator(Migrator):
    name = "CDT Migrator"
    rerender = True
    migrator_version = 1

    def filter_not_in_migration(self, attrs, not_bad_str_start=""):
        if super().filter_not_in_migration(attrs, not_bad_str_start):
            return True

        # we need to check if there is any cdt package as dependency
        requirements = attrs.get("requirements", {})

        rq = requirements.get("build", set()) | requirements.get("host", set())

        return "cdt_stub" not in rq

    def migrate(
        self, recipe_dir: str, attrs: AttrsTypedDict, **kwargs: Any
    ) -> MigrationUidTypedDict:
        with pushd(recipe_dir):
            self.set_build_number("meta.yaml")

            with open("meta.yaml") as fp:
                yaml = fp.read()

            # Rewrite the recipe file
            with open("meta.yaml", "w") as fp:
                fp.write(yaml)

        # TODO: remove duplicate libgl entries

        return self.migrator_uid(attrs)

    def pr_body(
        self, feedstock_ctx: ClonedFeedstockContext, add_label_text: bool = True
    ) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            textwrap.dedent(
                """\

""",
            )
        )
        return body

    def commit_message(self, feedstock_ctx) -> str:
        return "Migrate CDT dependencies to regular feedstocks"

    def pr_title(self, feedstock_ctx) -> str:
        return "Migrate CDT dependencies to regular feedstocks"

    def remote_branch(self, feedstock_ctx) -> str:
        return f"{self.name}-migration-{self.migrator_version}"

    def migrator_uid(self, attrs):
        if self.name is None:
            raise ValueError("name is None")
        n = super().migrator_uid(attrs)
        n["name"] = self.name
        return n
