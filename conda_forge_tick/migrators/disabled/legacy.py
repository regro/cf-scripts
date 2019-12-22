# type: ignore

import os
import re
from itertools import chain
from textwrap import dedent
from typing import Any, Optional, Set, List

import networkx as nx
from conda_smithy.configure_feedstock import get_cfp_file_path
from conda_smithy.update_cb3 import update_cb3
from ruamel.yaml import safe_load, safe_dump

from conda_forge_tick.contexts import FeedstockContext
from conda_forge_tick.migrators.core import Migrator, GraphMigrator
from conda_forge_tick.utils import UniversalSet
from conda_forge_tick.xonsh_utils import indir

from rever.tools import eval_version, hash_url, replace_in_file

class JS(Migrator):
    """Migrator for JavaScript syntax"""

    patterns = [
        (
            "meta.yaml",
            r"  script: npm install -g \.",
            "  script: |\n"
            "    tgz=$(npm pack)\n" "    npm install -g $tgz",
        ),
        ("meta.yaml", "   script: |\n", "  script: |"),
    ]

    migrator_version = 0

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        conditional = super().filter(attrs)
        return bool(
            conditional
            or (
                (attrs.get("meta_yaml", {}).get("build", {}).get("noarch") != "generic")
                or (
                    attrs.get("meta_yaml", {}).get("build", {}).get("script")
                    != "npm install -g ."
                )
            )
            and "  script: |" in attrs.get("raw_meta_yaml", "").split("\n"),
        )

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        with indir(recipe_dir):
            for f, p, n in self.patterns:
                p = eval_version(p)
                n = eval_version(n)
                replace_in_file(p, n, f, leading_whitespace=False)
            self.set_build_number("meta.yaml")
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            "It is very likely that this feedstock is in need of migration.\n"
            "Notes and instructions for merging this PR:\n"
            "1. Please merge the PR only after the tests have passed. \n"
            "2. Feel free to push to the bot's branch to update this PR if needed. \n",
        )
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return "migrated to new npm build"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return "Migrate to new npm build"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return "npm_migration"


class Compiler(Migrator):
    """Migrator for Jinja2 comiler syntax."""

    migrator_version = 0

    rerender = True

    compilers = {
        "toolchain",
        "toolchain3",
        "gcc",
        "cython",
        "pkg-config",
        "autotools",
        "make",
        "cmake",
        "autconf",
        "libtool",
        "m4",
        "ninja",
        "jom",
        "libgcc",
        "libgfortran",
    }

    def __init__(self, pr_limit: int = 0):
        super().__init__(pr_limit)
        self.cfp = get_cfp_file_path()[0]

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        for req in attrs.get("req", []):
            if req.endswith("_compiler_stub"):
                return True
        conditional = super().filter(attrs)
        return conditional or not any(x in attrs.get("req", []) for x in self.compilers)

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        with indir(recipe_dir):
            content, self.messages = update_cb3("meta.yaml", self.cfp)
            with open("meta.yaml", "w") as f:
                f.write(content)
            self.set_build_number("meta.yaml")
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            "{}\n"
            "*If you have recived a `Migrate to Jinja2 compiler "
            "syntax` PR from me recently please close that one and use "
            "this one*.\n"
            "It is very likely that this feedstock is in need of migration.\n"
            "Notes and instructions for merging this PR:\n"
            "1. Please merge the PR only after the tests have passed. \n"
            "2. Feel free to push to the bot's branch to update this PR if needed. \n"
            "3. If this recipe has a `cython` dependency please note that only a `C`"
            " compiler has been added. If the project also needs a `C++` compiler"
            " please add it by adding `- {{ compiler('cxx') }}` to the build section \n".format(
                self.messages,
            ),
        )
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return "migrated to Jinja2 compiler syntax build"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return "Migrate to Jinja2 compiler syntax"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return "compiler_migration2"


class Noarch(Migrator):
    """Migrator for adding noarch."""

    migrator_version = 0

    compiler_pat = re.compile(".*_compiler_stub")
    sel_pat = re.compile(r"(.+?)\s*(#.*)?\[([^\[\]]+)\](?(2)[^\(\)]*)$")
    unallowed_reqs = ["toolchain", "toolchain3", "gcc", "cython", "clangdev"]
    checklist = [
        "No compiled extensions",
        "No post-link or pre-link or pre-unlink scripts",
        "No OS specific build scripts",
        "No python version specific requirements",
        "No skips except for python version. (If the recipe is py3 only, remove skip statement and add version constraint on python)",
        "2to3 is not used",
        "Scripts argument in setup.py is not used",
        "If entrypoints are in setup.py, they are listed in meta.yaml",
        "No activate scripts",
        "Not a dependency of `conda`",
    ]

    rerender = True

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        conditional = (
            super().filter(attrs)
            or attrs.get("meta_yaml", {}).get("outputs")
            or attrs.get("meta_yaml", {}).get("build", {}).get("noarch")
        )
        if conditional:
            return True
        python = False
        for req in attrs.get("req", []):
            if self.compiler_pat.match(req) or req in self.unallowed_reqs:
                return True
            if req == "python":
                python = True
        if not python:
            return True
        for line in attrs.get("raw_meta_yaml", "").splitlines():
            if self.sel_pat.match(line):
                return True

        # Not a dependency of `conda`
        if attrs["feedstock_name"] in nx.ancestors(self.ctx.parent.graph, "conda"):
            return True

        return False

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        with indir(recipe_dir):
            build_idx = [l.rstrip() for l in attrs["raw_meta_yaml"].split("\n")].index(
                "build:",
            )
            line = attrs["raw_meta_yaml"].split("\n")[build_idx + 1]
            spaces = len(line) - len(line.lstrip())
            replace_in_file(
                "build:",
                "build:\n{}noarch: python".format(" " * spaces),
                "meta.yaml",
                leading_whitespace=False,
            )
            replace_in_file(
                "script:.+?",
                "script: python -m pip install --no-deps --ignore-installed .",
                "meta.yaml",
            )
            replace_in_file(
                "  build:", "  host:", "meta.yaml", leading_whitespace=False,
            )
            if "pip" not in attrs["req"]:
                replace_in_file(
                    "  host:",
                    "  host:\n    - pip",
                    "meta.yaml",
                    leading_whitespace=False,
                )
            self.set_build_number("meta.yaml")
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            "I think this feedstock could be built with noarch.\n"
            "This means that the package only needs to be built "
            "once, drastically reducing CI usage.\n"
            "See [here](https://conda-forge.org/docs/meta.html#building-noarch-packages) "
            "for more information about building noarch packages.\n"
            "Before merging this PR make sure:\n{}\n"
            "Notes and instructions for merging this PR:\n"
            "1. If any items in the above checklist are not satisfied, "
            "please close this PR. Do not merge. \n"
            "2. Please merge the PR only after the tests have passed. \n"
            "3. Feel free to push to the bot's branch to update this PR if needed. \n",
        )
        body = body.format("\n".join(["- [ ] " + item for item in self.checklist]))
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return "add noarch"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return "Suggestion: add noarch"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return "noarch_migration"


class NoarchR(Noarch):
    migrator_version = 0
    rerender = True
    bump_number = 1

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        conditional = (
            Migrator.filter(self, attrs)
            or attrs.get("meta_yaml", {}).get("outputs")
            or attrs.get("meta_yaml", {}).get("build", {}).get("noarch")
        )
        if conditional:
            return True
        r = False
        for req in attrs.get("req", []):
            if self.compiler_pat.match(req) or req in self.unallowed_reqs:
                return True

        if attrs["feedstock_name"].startswith("r-"):
            r = True
        if not r:
            return True

        # R recipes tend to have some things in their build / test that have selectors

        # for line in attrs.get('raw_meta_yaml', '').splitlines():
        #    if self.sel_pat.match(line):
        #        return True
        return False

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        check_for = ["toolchain", "libgcc", "compiler"]

        noarch = not any(c in attrs["raw_meta_yaml"] for c in check_for)

        r_pkg_name = attrs["feedstock_name"][2:]
        r_noarch_build_sh = dedent(
            """
        #!/bin/bash
        if [[ $target_platform =~ linux.* ]] || [[ $target_platform == win-32 ]] || [[ $target_platform == win-64 ]] || [[ $target_platform == osx-64 ]]; then
          export DISABLE_AUTOBREW=1
          mv DESCRIPTION DESCRIPTION.old
          grep -v '^Priority: ' DESCRIPTION.old > DESCRIPTION
          $R CMD INSTALL --build .
        else
          mkdir -p $PREFIX/lib/R/library/{r_pkg_name}
          mv * $PREFIX/lib/R/library/{r_pkg_name}
        fi
        """
        ).format(r_pkg_name=r_pkg_name)

        with indir(recipe_dir):
            if noarch:
                with open("build.sh", "w") as f:
                    f.writelines(r_noarch_build_sh)
            new_text = ""
            with open("meta.yaml", "r") as f:
                lines = f.readlines()
                lines_stripped = [line.rstrip() for line in lines]
                if noarch and "build:" in lines_stripped:
                    index = lines_stripped.index("build:")
                    spacing = 2
                    s = len(lines[index + 1].lstrip()) - len(lines[index + 1])
                    if s > 0:
                        spacing = s
                    lines[index] = lines[index] + " " * spacing + "noarch: generic\n"
                regex_unix1 = re.compile(
                    r"license_file: '{{ environ\[\"PREFIX\"\] }}/lib/R/share/licenses/(\S+)'\s+# \[unix\]",
                )
                regex_unix2 = re.compile(
                    r"license_file: '{{ environ\[\"PREFIX\"\] }}/lib/R/share/licenses/(.+)'\s+# \[unix\]",
                )
                regex_win = re.compile(
                    r"license_file: '{{ environ\[\"PREFIX\"\] }}\\R\\share\\licenses\\(\S+)'\s+# \[win\]",
                )
                for i, line in enumerate(lines_stripped):
                    if noarch and line.lower().strip().startswith("skip: true"):
                        lines[i] = ""
                    # Fix path to licenses
                    if regex_unix1.match(line.strip()):
                        lines[i] = regex_unix1.sub(
                            "license_file: '{{ environ[\"PREFIX\"] }}/lib/R/share/licenses/\\1'",
                            lines[i],
                        )
                    if regex_unix2.match(line.strip()):
                        lines[i] = regex_unix2.sub(
                            "license_file: '{{ environ[\"PREFIX\"] }}/lib/R/share/licenses/\\1'",
                            lines[i],
                        )
                    if regex_win.match(line.strip()):
                        lines[i] = ""

                new_text = "".join(lines)
            if new_text:
                with open("meta.yaml", "w") as f:
                    f.writelines(new_text)
            self.set_build_number("meta.yaml")
        return self.migrator_uid(attrs)

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            "It is likely this feedstock needs to be rebuilt.\n"
            "Notes and instructions for merging this PR:\n"
            "1. Please merge the PR only after the tests have passed. \n"
            "2. Feel free to push to the bot's branch to update this PR if needed. \n"
            "{}\n",
        )
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return "add noarch r"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        if self.name:
            return "Noarch R for " + self.name
        else:
            return "Bump build number"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return "r-noarch"


class Rebuild(GraphMigrator):
    """Migrator for bumping the build number."""

    migrator_version = 0
    rerender = True
    bump_number = 1

    # TODO: add a description kwarg for the status page at some point.
    def __init__(
        self,
        graph: nx.DiGraph = None,
        name: Optional[str] = None,
        pr_limit: int = 0,
        top_level: Set["PackageName"] = None,
        cycles: Optional[List["PackageName"]] = None,
        obj_version: Optional[int] = None,
    ):
        super().__init__(pr_limit=pr_limit, obj_version=obj_version, graph=graph)
        self.name = name
        self.top_level = top_level
        self.cycles = set(chain.from_iterable(cycles or []))

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        with indir(recipe_dir):
            self.set_build_number("meta.yaml")
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        additional_body = (
            "This PR has been triggered in an effort to update **{}**.\n\n"
            "Notes and instructions for merging this PR:\n"
            "1. Please merge the PR only after the tests have passed. \n"
            "2. Feel free to push to the bot's branch to update this PR if needed. \n"
            "**Please note that if you close this PR we presume that "
            "the feedstock has been rebuilt, so if you are going to "
            "perform the rebuild yourself don't close this PR until "
            "the your rebuild has been merged.**\n\n"
            "This package has the following downstream children:\n"
            "{}\n"
            "And potentially more."
            "".format(self.name, "\n".join(self.downstream_children(feedstock_ctx)))
        )
        body = body.format(additional_body)
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return "bump build number"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        if self.name:
            return "Rebuild for " + self.name
        else:
            return "Bump build number"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        s_obj = str(self.obj_version) if self.obj_version else ""
        return (
            "rebuild"
            + (self.name.lower().replace(" ", "_") if self.name else "")
            + str(self.migrator_version)
            + s_obj
        )

    def migrator_uid(self, attrs: "AttrsTypedDict") -> "MigrationUidTypedDict":
        n = super().migrator_uid(attrs)
        if isinstance(self.name, str):
            n["name"] = self.name
        return n

    def order(self, graph: nx.DiGraph, total_graph: nx.DiGraph) -> List["PackageName"]:
        """Run the order by number of decendents, ties are resolved by package name"""
        return sorted(
            graph, key=lambda x: (len(nx.descendants(total_graph, x)), x), reverse=True,
        )


class Pinning(Migrator):
    """Migrator for remove pinnings for specified requirements."""

    migrator_version = 0
    rerender = True

    def __init__(
        self, pr_limit: int = 0, removals: Optional[Set["PackageName"]] = None,
    ):
        super().__init__(pr_limit)
        self.removals: Set
        if removals is None:
            self.removals = UniversalSet()
        else:
            self.removals = set(removals)

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        return (
            super().filter(attrs) or len(attrs.get("req", set()) & self.removals) == 0
        )

    def migrate(
        self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any
    ) -> "MigrationUidTypedDict":
        remove_pins = attrs.get("req", set()) & self.removals
        remove_pats = {
            req: re.compile(rf"\s*-\s*{req}.*?(\s+.*?)(\s*#.*)?$")
            for req in remove_pins
        }
        self.removed = {}
        with open(os.path.join(recipe_dir, "meta.yaml")) as f:
            raw = f.read()
        lines = raw.splitlines()
        n = False
        for i, line in enumerate(lines):
            for k, p in remove_pats.items():
                m = p.match(line)
                if m is not None:
                    lines[i] = lines[i].replace(m.group(1), "")
                    removed_version = m.group(1).strip()
                    if not n:
                        n = bool(removed_version)
                    if removed_version:
                        self.removed[k] = removed_version
        if not n:
            return False
        upd = "\n".join(lines) + "\n"
        with open(os.path.join(recipe_dir, "meta.yaml"), "w") as f:
            f.write(upd)
        self.set_build_number(os.path.join(recipe_dir, "meta.yaml"))
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            "I noticed that this recipe has version pinnings that may not be needed.\n"
            "I have removed the following pinnings:\n"
            "{}\n"
            "Notes and instructions for merging this PR:\n"
            "1. Make sure that the removed pinnings are not needed. \n"
            "2. Please merge the PR only after the tests have passed. \n"
            "3. Feel free to push to the bot's branch to update this PR if "
            "needed. \n".format(
                "\n".join([f"{n}: {p}" for n, p in self.removed.items()]),
            ),
        )
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return "remove version pinnings"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return "Suggestion: remove version pinnings"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        return "pinning"


class BlasRebuild(Rebuild):
    """Migrator for rebuilding for blas 2.0."""

    migrator_version = 0
    rerender = True
    bump_number = 1

    blas_patterns = [
        re.compile(r"(\s*?)-\s*(blas|openblas|mkl|(c?)lapack)"),
        re.compile(r'(\s*?){%\s*set variant\s*=\s*"openblas"?\s*%}'),
    ]

    def __init__(
        self,
        graph=None,
        name=None,
        pr_limit: int = 0,
        top_level=None,
        cycles=None,
        obj_version=None,
    ):
        super().__init__(
            graph=graph,
            name="blas2",
            pr_limit=pr_limit,
            top_level=top_level,
            cycles=cycles,
            obj_version=obj_version,
        )

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs):
        with indir(recipe_dir):
            # Update build number
            # Remove blas related packages and features
            with open("meta.yaml", "r") as f:
                lines = f.readlines()
            reqs_line = "build:"
            for i, line in enumerate(lines):
                if line.strip() == "host:":
                    reqs_line = "host:"
                for blas_pattern in self.blas_patterns:
                    m = blas_pattern.match(line)
                    if m is not None:
                        lines[i] = ""
                        break
            for i, line in enumerate(lines):
                sline = line.lstrip()
                if len(sline) != len(line) and line.strip() == reqs_line:
                    for dep in ["libblas", "libcblas"]:
                        print(lines[i], len(line) - len(sline))
                        lines[i] = (
                            lines[i]
                            + " " * (len(line) - len(sline))
                            + "  - "
                            + dep
                            + "\n"
                        )
            new_text = "".join(lines)
            with open("meta.yaml", "w") as f:
                f.write(new_text)
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        additional_body = (
            "This PR has been triggered in an effort to update for new BLAS scheme.\n\n"
            "New BLAS scheme builds conda packages against the Reference-LAPACK's libraries\n"
            "which allows to change the BLAS implementation at install time by the user.\n\n"
            "Checklist:\n"
            "1. Tests has passed. \n"
            "2. Added `liblapack, liblapacke` if they are needed. \n"
            "3. Removed `libcblas` if `cblas_*` API is not used. \n"
            "Feel free to push to the bot's branch to update this PR if needed. \n"
            "**Please note that if you close this PR we presume that "
            "the feedstock has been rebuilt, so if you are going to "
            "perform the rebuild yourself don't close this PR until "
            "the your rebuild has been merged.**\n\n"
            "This package has the following downstream children:\n"
            "{children}\n"
            "And potentially more."
            "".format(children="\n".join(self.downstream_children(feedstock_ctx)))
        )
        body = body.format(additional_body)
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return "Rebuild for new BLAS scheme"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return "Rebuild for new BLAS scheme"


class RBaseRebuild(Rebuild):
    """Migrator for rebuilding all R packages."""

    migrator_version = 0
    rerender = True
    bump_number = 1

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs):
        # Set the provider to Azure only
        with indir(recipe_dir + "/.."):
            if os.path.exists("conda-forge.yml"):
                with open("conda-forge.yml", "r") as f:
                    y = safe_load(f)
            else:
                y = {}
            if "provider" not in y:
                y["provider"] = {}
            y["provider"]["win"] = "azure"
            with open("conda-forge.yml", "w") as f:
                safe_dump(y, f)

        with indir(recipe_dir):
            with open("meta.yaml", "r") as f:
                text = f.read()

            changed = False
            lines = text.split("\n")

            if (
                attrs["feedstock_name"].startswith("r-")
                and "- conda-forge/r" not in text
                and any(
                    a in text
                    for a in [
                        "johanneskoester",
                        "bgruening",
                        "daler",
                        "jdblischak",
                        "cbrueffer",
                        "dbast",
                        "dpryan79",
                    ]
                )
            ):
                for i, line in enumerate(lines):
                    if line.strip() == "recipe-maintainers:" and i + 1 < len(lines):
                        lines[i] = (
                            line
                            + "\n"
                            + lines[i + 1][: lines[i + 1].index("-")]
                            + "- conda-forge/r"
                        )

                changed = True

            for i, line in enumerate(lines):
                if line.lstrip().startswith("- {{native}}toolchain"):
                    replaced_lines = []
                    for comp in ["c", "cxx", "fortran"]:
                        if "compiler('" + comp + "')" in text:
                            replaced_lines.append(
                                line.replace(
                                    "- {{native}}toolchain",
                                    "- {{ compiler('m2w64_" + comp + "') }}",
                                ),
                            )
                    if len(replaced_lines) != 0:
                        lines[i] = "\n".join(replaced_lines)
                        changed = True
                        break

            if changed:
                with open("meta.yaml", "w") as f:
                    f.write("\n".join(lines))

        return super().migrate(recipe_dir, attrs)


class GFortranOSXRebuild(Rebuild):
    migrator_version = 0
    rerender = True
    bump_number = 1

    def pr_body(self, feedstock_ctx: FeedstockContext) -> str:
        body = super(Rebuild, self).pr_body(feedstock_ctx)
        additional_body = (
            "This PR has been triggered in an effort to update **{0}**.\n\n"
            "Notes and instructions for merging this PR:\n"
            "1. Please merge the PR only after the tests have passed. \n"
            "2. Feel free to push to the bot's branch to update this PR if needed. \n"
            "**Please note that if you close this PR we presume that "
            "the feedstock has been rebuilt, so if you are going to "
            "perform the rebuild yourself don't close this PR until "
            "the your rebuild has been merged.**\n\n"
            "This package has the following downstream children:\n"
            "{children}\n"
            "And potentially more."
            "".format(
                "to gfortran 7 for OSX",
                children="\n".join(self.downstream_children(feedstock_ctx)),
            )
        )
        body = body.format(additional_body)
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        return "Rebuild for gfortran 7 for OSX"

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return "Rebuild for gfortran 7 for OSX"