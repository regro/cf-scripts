import re
import textwrap
from itertools import chain
from typing import Any

from conda_forge_tick.contexts import ClonedFeedstockContext
from conda_forge_tick.migrators.core import Migrator
from conda_forge_tick.migrators_types import AttrsTypedDict, MigrationUidTypedDict
from conda_forge_tick.os_utils import pushd

cdt_mapping = {
    "alsa-lib-devel": "alsa-lib",
    "at-spi-devel": None,
    "atk-devel": "atk-1.0",
    "audit-libs-devel": None,
    "cairo-devel": "cairo",
    "cracklib-devel": None,
    "cups-devel": "libcups",
    "expat-devel": "expat",
    "fontconfig-devel": "fontconfig",
    "freetype-devel": "freetype",
    "glib2-devel": "glib",
    "gtk2-devel": "gtk2",
    "gtkmm24-devel": None,
    "kmod-devel": None,
    "libbonobo-devel": None,
    "libdrm-devel": "libdrm",
    "libeconf-devel": None,
    "libglvnd-core-devel": "libglvnd-devel",
    "libglvnd-devel": "libglvnd-devel",
    "libibmad-devel": "rmda-core",
    "libice-devel": "xorg-libice",
    "libidl-devel": None,
    "libnl-devel": "libnl <3",
    "libnl3-devel": "libnl",
    "libpng-devel": "libpng",
    "libpwquality-devel": None,
    "libselinux-devel": None,
    "libsepol-devel": None,
    "libsm-devel": "xorg-libsm",
    "libsoup-devel": "libsoup <3",
    "libudev-devel": "libudev",
    "libuuid-devel": "libuuid",
    "libx11-devel": "xorg-libx11",
    "libxau-devel": "xorg-libxau",
    "libxcb-devel": "xorg-libxcb",
    "libxcomposite-devel": "xorg-libxcomposite",
    "libxcursor-devel": "xorg-libxcursor",
    "libxdamage-devel": "xorg-libxdamage",
    "libxext-devel": "xorg-libxext",
    "libxfixes-devel": "xorg-libxfixes",
    "libxft-devel": "xorg-libxft",
    "libxi-devel": "xorg-libxi",
    "libxinerama-devel": "xorg-libxinerama",
    "libxkbcommon-devel": "libxkbcommon",
    "libxml2-devel": "libxml2",
    "libxrandr-devel": "xorg-librandr",
    "libxrender-devel": "xorg-libxrender",
    "libxscrnsaver-devel": "xorg-libxscrnsaver",
    "libxshmfence-devel": "xorg-libxshmfence",
    "libxt-devel": "xorg-libxt",
    "libxtst-devel": "xorg-libxtst",
    "libxxf86vm-devel": "xorg-libxxf86vm",
    "mesa-khr-devel": "libgl-devel",
    "mesa-libegl-devel": "libegl-devel",
    "mesa-libgbm-devel": None,
    "mesa-libgl-devel": "libgl-devel",
    "mesa-libglu-devel": "libglu",
    "numactl-devel": "libnuma",
    "opensm-devel": None,
    "orbit2-devel": None,
    "pam-devel": None,
    "pango-devel": "pango",
    "pciutils-devel": "",
    "pixman-devel": "pixman",
    "rdma-core-devel": "rdma-core",
    "systemd-devel": "libsystemd",
    "xcb-util-devel": "xcb-util",
    "xcb-util-image-devel": "xcb-util-image",
    "xcb-util-keysyms-devel": "xcb-util-keysyms",
    "xcb-util-renderutil-devel": "xcb-util-renderutil",
    "xcb-util-wm-devel": "xcb-util-wm",
    "xorg-x11-proto-devel": "xorgproto",
}


class CDTMigrator(Migrator):
    name = "CDT Migrator"
    rerender = True
    migrator_version = 1

    def filter_not_in_migration(self, attrs, not_bad_str_start=""):
        if super().filter_not_in_migration(attrs, not_bad_str_start):
            return True

        # we need to check if there is any cdt package as dependency
        for key, reqs in attrs.get("requirements", {}).items():
            if "cdt_stub" in reqs:
                return False

        return True

    def migrate(
        self, recipe_dir: str, attrs: AttrsTypedDict, **kwargs: Any
    ) -> MigrationUidTypedDict:
        cdt_pattern = re.compile(
            r"^ (?P<pre_cdt> .*)"
            r"(?P<full_cdt> \{\{ \s* cdt\( ['\"] (?P<cdt> .+?) ['\"] \) \s* \}\})"
            r"(?P<post_cdt> .*?) (?P<selector> \#.*)? $",
            re.VERBOSE,
        )

        with pushd(recipe_dir):
            self.set_build_number("meta.yaml")

            with open("meta.yaml") as fp:
                yaml = fp.readlines()

            # Locate all requirement sections.
            # (start, end)
            requirement_ranges: list[tuple[int, int]] = []
            req_start: int | None = None
            req_indent: str | None = None
            for lineno, line in enumerate(yaml):
                if req_start is not None:
                    assert req_indent is not None
                    if line.strip() and not line.startswith(req_indent):
                        requirement_ranges.append((req_start + 1, lineno))
                        req_start = None

                line_lstrip = line.lstrip()
                if line_lstrip.rstrip() in ("requirements:", "requires:"):
                    req_start = lineno
                    req_indent = (len(line) - len(line_lstrip) + 1) * " "
            if req_start is not None:
                requirement_ranges.append((req_start + 1, lineno + 1))

            # Process requirement sections in reverse order, to avoid changing linenos.
            for req_start, req_end in reversed(requirement_ranges):
                req_section = yaml[req_start:req_end]

                # Locate subsections.
                subsections: dict[str | None, list[str]] = {}
                req_iter = iter(req_section)
                current_section: str | None = None
                current_section_start: int = 0
                for lineno, line in enumerate(req_iter):
                    if not line.strip():
                        continue
                    first_word = line.split(maxsplit=1)[0]
                    if first_word.endswith(":"):
                        subsections[current_section] = req_section[
                            current_section_start:lineno
                        ]
                        current_section = first_word
                        current_section_start = lineno
                subsections[current_section] = req_section[
                    current_section_start : lineno + 1
                ]

                for key, subsection in subsections.items():
                    new = []
                    seen = set()
                    # Perform CDT replacement.
                    for line in subsection:
                        if (match := cdt_pattern.match(line)) is None:
                            new.append(line)
                            continue

                        if replacement := cdt_mapping.get(match.group("cdt").lower()):
                            # Do not include the same package twice.
                            if replacement in seen:
                                continue
                            seen.add(replacement)
                            extra_ws_len = len(match.group("full_cdt")) - len(
                                replacement
                            )
                            extra_ws = "" if extra_ws_len <= 0 else extra_ws_len * " "
                            # Move build: CDTs to host:. If there is no "host" section, create one.
                            target = (
                                subsections.setdefault(
                                    "host:", [subsection[0].replace(key, "host:")]
                                )
                                if key == "build:"
                                else new
                            )
                            target.append(
                                f"{match.group('pre_cdt')}"
                                f"{replacement}"
                                f"{extra_ws}"
                                f"{match.group('post_cdt')}"
                                f"{match.group('selector')}"
                                "\n"
                            )
                    subsections[key] = new

                # Reconstruct the requirement section.
                yaml[req_start:req_end] = chain.from_iterable(subsections.values())

            # Rewrite the recipe file
            with open("meta.yaml", "w") as fp:
                fp.write("".join(yaml))

        # TODO: remove duplicate libgl entries

        return self.migrator_uid(attrs)

    def pr_body(
        self, feedstock_ctx: ClonedFeedstockContext, add_label_text: bool = True
    ) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            textwrap.dedent(
                """\
The [Core Dependency Tree (CDT) packages are being phased out](https://github.com/conda-forge/cdt-builds/issues/89).
This migrator will attempt to replace the CDT dependencies with regular conda-forge packages.
""",
            )
        )
        return body

    def commit_message(self, feedstock_ctx) -> str:
        return "Migrate CDT dependencies to regular packages"

    def pr_title(self, feedstock_ctx) -> str:
        return "Migrate CDT dependencies to regular packages"

    def remote_branch(self, feedstock_ctx) -> str:
        return f"{self.name}-migration-{self.migrator_version}"

    def migrator_uid(self, attrs):
        if self.name is None:
            raise ValueError("name is None")
        n = super().migrator_uid(attrs)
        n["name"] = self.name
        return n
