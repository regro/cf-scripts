import functools
import logging
import os
import textwrap
import typing
from typing import Any, Sequence

import networkx as nx
from conda.models.version import VersionOrder
from conda_build.config import Config
from conda_build.variants import parse_config_file

from conda_forge_tick.contexts import ClonedFeedstockContext
from conda_forge_tick.migrators.core import Migrator, MiniMigrator, _skip_due_to_schema
from conda_forge_tick.migrators.libboost import _slice_into_output_sections
from conda_forge_tick.os_utils import pushd

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _get_curr_python_min():
    with pushd(os.environ["CONDA_PREFIX"]):
        pinnings = parse_config_file(
            "conda_build_config.yaml",
            config=Config(),
        )
    pymin = pinnings.get("python_min", None)
    if pymin is None or len(pymin) == 0:
        return None
    else:
        return pymin[0]


def _has_noarch_python(lines):
    for line in lines:
        if line.lstrip().startswith("noarch: python"):
            return True
    return False


def _has_build_section(lines):
    for line in lines:
        if line.lstrip().startswith("build:"):
            return True
    return False


def _process_req_list(section, req_list_name, new_python_req, force_apply=False):
    found_it = False
    new_lines = []
    curr_indent = None
    in_section = False
    adjusted_python = False
    python_min_override = None
    for line in section:
        lstrip_line = line.lstrip()

        # skip comments
        if (
            lstrip_line.startswith("#")
            or line.strip() == ""
            or lstrip_line.startswith("{#")
        ):
            new_lines.append(line)
            continue

        indent = len(line) - len(lstrip_line)
        if curr_indent is None:
            curr_indent = indent

        if in_section:
            if indent < curr_indent:
                if not adjusted_python and req_list_name not in ["host", "run"]:
                    logger.debug("adding python to section %s", req_list_name)
                    # insert python as spec
                    new_line = curr_indent * " " + "- python " + new_python_req + "\n"
                    new_lines.append(new_line)

                # the section ended
                in_section = False
                new_line = line
            else:
                indent_to_keep, spec_and_comment = line.split("-", maxsplit=1)
                spec_and_comment = spec_and_comment.split("#", maxsplit=1)
                if len(spec_and_comment) == 1:
                    spec = spec_and_comment[0]
                    comment = ""
                else:
                    spec, comment = spec_and_comment
                spec = spec.strip()
                comment = comment.strip()

                name_and_req = spec.split(" ", maxsplit=1)
                if len(name_and_req) == 1:
                    name = name_and_req[0]
                    req = ""
                else:
                    name, req = name_and_req

                name = name.strip()
                req = req.strip()
                logger.debug(
                    "requirement line decomp: indent='%s', name='%s', req='%s', comment='%s'",
                    indent_to_keep,
                    name,
                    req,
                    comment,
                )

                if name == "python" and (force_apply or req == ""):
                    adjusted_python = True
                    new_line = (
                        indent_to_keep
                        + "- python "
                        + new_python_req
                        + ("  # " + comment if comment != "" else "")
                        + "\n"
                    )
                    if req.startswith(">="):
                        python_min_override = req[2:].strip()

                else:
                    new_line = line
        else:
            if line.lstrip().startswith(req_list_name + ":"):
                logger.debug("found %s for processing req list", req_list_name)
                in_section = True
                found_it = True

            new_line = line

        new_lines.append(new_line)
        curr_indent = indent

    return found_it, new_lines, python_min_override


def _add_test_requires(section):
    new_lines = []
    in_test = False
    test_indent = None
    for line in section:
        lstrip_line = line.lstrip()

        # skip comments
        if (
            lstrip_line.startswith("#")
            or line.strip() == ""
            or lstrip_line.startswith("{#")
        ):
            new_lines.append(line)
            continue

        indent = len(line) - len(lstrip_line)

        if lstrip_line.startswith("test:"):
            logger.debug("found test section for adding requires")
            in_test = True
            test_indent = indent
            new_lines.append(line)
            continue

        if in_test:
            indent_size = indent - test_indent
            requires_lines = [
                (" " * indent) + "requires:" + "\n",
                (" " * (indent + indent_size)) + "- python {{ python_min }}" + "\n",
            ]
            new_lines += requires_lines
            new_lines.append(line)

            in_test = False
        else:
            new_lines.append(line)

    return new_lines


def _process_section(section, force_noarch_python=False, force_apply=False):
    if (not _has_noarch_python(section)) and (not force_noarch_python):
        return section, None

    found_it, section, python_min_override = _process_req_list(
        section, "host", "{{ python_min }}", force_apply=force_apply
    )
    logger.debug("applied `noarch: python` host? %s", found_it)
    found_it, section, _ = _process_req_list(
        section, "run", ">={{ python_min }}", force_apply=force_apply
    )
    logger.debug("applied `noarch: python` to run? %s", found_it)
    found_it, section, _ = _process_req_list(
        section,
        "requires",
        "{{ python_min }}",
        force_apply=force_apply,
    )
    logger.debug("applied `noarch: python` to test.requires? %s", found_it)
    if not found_it:
        section = _add_test_requires(section)

    return section, python_min_override


def _apply_noarch_python_min(
    recipe_dir: str,
    attrs: "AttrsTypedDict",
    preserve_existing_specs: bool = True,
) -> None:
    fname = os.path.join(recipe_dir, "meta.yaml")
    if os.path.exists(fname):
        with open(fname) as fp:
            lines = fp.readlines()

        python_min_override = set()
        new_lines = []
        sections = _slice_into_output_sections(lines, attrs)
        output_indices = sorted(list(sections.keys()))
        has_global_noarch_python = _has_noarch_python(sections[-1])
        for output_index in output_indices:
            section = sections[output_index]
            has_build_override = _has_build_section(section) and (output_index != -1)
            # _process_section returns list of lines already
            _new_lines, _python_min_override = _process_section(
                section,
                force_noarch_python=has_global_noarch_python
                and (not has_build_override),
                force_apply=not preserve_existing_specs,
            )
            new_lines += _new_lines
            if _python_min_override is not None:
                python_min_override.add(_python_min_override)

        if python_min_override and not preserve_existing_specs:
            python_min_override.add(_get_curr_python_min())
            ok_versions = set()
            for ver in python_min_override:
                try:
                    VersionOrder(ver.replace("-", "."))
                    ok_versions.add(ver)
                except Exception as e:
                    logger.error(
                        "found invalid python min version: %s", ver, exc_info=e
                    )
            if ok_versions:
                python_min_version = max(
                    ok_versions,
                    key=lambda x: VersionOrder(x.replace("-", ".")),
                )
                logger.debug(
                    "found python min version: %s (global min is %s)",
                    python_min_version,
                    _get_curr_python_min(),
                )
                if python_min_version != _get_curr_python_min():
                    new_lines = [
                        f"{{% set python_min = '{python_min_version}' %}}\n"
                    ] + new_lines
        with open(fname, "w") as fp:
            fp.write("".join(new_lines))


class NoarchPythonMinCleanup(MiniMigrator):
    post_migration = True

    def __init__(self, preserve_existing_specs: bool = True):
        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {"preserve_existing_specs": preserve_existing_specs}

        self.preserve_existing_specs = preserve_existing_specs

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """If True SKIP the node"""
        has_noarch_python = False
        has_python_min = False
        for line in attrs.get("raw_meta_yaml", "").splitlines():
            if line.lstrip().startswith("noarch: python"):
                has_noarch_python = True
            if "{{ python_min }}" in line:
                has_python_min = True

        needs_migration = has_noarch_python and (not has_python_min)

        return (not needs_migration) or _skip_due_to_schema(
            attrs, self.allowed_schema_versions
        )

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        _apply_noarch_python_min(
            recipe_dir, attrs, preserve_existing_specs=self.preserve_existing_specs
        )


class NoarchPythonMinMigrator(Migrator):
    """Migrator for converting `noarch: python` recipes to the CFEP-25 syntax."""

    bump_number = 1

    def __init__(
        self,
        *,
        pr_limit: int = 10,
        graph: nx.DiGraph = None,
        effective_graph: nx.DiGraph = None,
        piggy_back_migrations: Sequence[MiniMigrator] | None = None,
    ):
        if not hasattr(self, "_init_args"):
            self._init_args = []

        if not hasattr(self, "_init_kwargs"):
            self._init_kwargs = {
                "pr_limit": pr_limit,
                "graph": graph,
                "effective_graph": effective_graph,
                "piggy_back_migrations": piggy_back_migrations,
            }

        super().__init__(
            pr_limit,
            graph=graph,
            effective_graph=effective_graph,
            piggy_back_migrations=[
                NoarchPythonMinCleanup(preserve_existing_specs=False)
            ]
            + (piggy_back_migrations or []),
        )
        self.name = "noarch_python_min"

        self._reset_effective_graph()

    def filter(self, attrs) -> bool:
        has_noarch_python = False
        has_python_min = False
        for line in attrs.get("raw_meta_yaml", "").splitlines():
            if line.lstrip().startswith("noarch: python"):
                has_noarch_python = True
            if "{{ python_min }}" in line:
                has_python_min = True

        needs_migration = has_noarch_python and (not has_python_min)

        return (
            super().filter(attrs)
            or (not needs_migration)
            or _skip_due_to_schema(attrs, self.allowed_schema_versions)
        )

    def migrate(self, recipe_dir, attrs, **kwargs):
        # the actual migration is done via a mini-migrator so that we can
        # apply this to other migrators as well
        self.set_build_number(os.path.join(recipe_dir, "meta.yaml"))
        return super().migrate(recipe_dir, attrs)

    def pr_body(self, feedstock_ctx: ClonedFeedstockContext) -> str:
        body = super().pr_body(feedstock_ctx)
        body = body.format(
            textwrap.dedent(
                """
            This PR updates the recipe to use the `noarch: python` syntax as described in
            [CFEP-25](https://github.com/conda-forge/cfep/blob/main/cfep-25.md). Please
            see the linked document for more information on the changes made.
            """,
            )
        )
        return body

    def commit_message(self, feedstock_ctx) -> str:
        return "update to CFEP-25 `noarch: python` syntax"

    def pr_title(self, feedstock_ctx) -> str:
        return "Rebuild for CFEP-25 `noarch: python` syntax"

    def remote_branch(self, feedstock_ctx) -> str:
        return f"{self.name}-migration-{self.migrator_version}"

    def migrator_uid(self, attrs):
        n = super().migrator_uid(attrs)
        n["name"] = self.name
        return n