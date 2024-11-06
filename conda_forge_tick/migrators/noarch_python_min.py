import logging
import os
import textwrap
import typing
from typing import Any, Sequence

import networkx as nx

from conda_forge_tick.contexts import ClonedFeedstockContext
from conda_forge_tick.migrators.core import Migrator, MiniMigrator, _skip_due_to_schema
from conda_forge_tick.migrators.libboost import _slice_into_output_sections

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

logger = logging.getLogger(__name__)


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
                    new_line = (
                        indent_to_keep
                        + "- python "
                        + new_python_req
                        + ("  #" + comment if comment != "" else "")
                    )
                    if line.endswith("\n"):
                        if not new_line.endswith("\n"):
                            new_line += "\n"
                    else:
                        if new_line.endswith("\n"):
                            new_line = new_line[:-1]
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

    return found_it, new_lines


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
            in_test = True
            test_indent = indent
            new_lines.append(line)
            continue

        if in_test:
            indent_size = indent - test_indent
            requires_lines = [
                (" " * indent) + "requires:",
                (" " * (indent + indent_size)) + "- python ={{ python_min }}",
            ]
            if line.endswith("\n"):
                requires_lines = [
                    _line + "\n" if not _line.endswith("\n") else _line
                    for _line in requires_lines
                ]
            else:
                requires_lines = [
                    _line[-1] if _line.endswith("\n") else _line
                    for _line in requires_lines
                ]

            new_lines += requires_lines
            new_lines.append(line)

            in_test = False
        else:
            new_lines.append(line)

    return new_lines


def _add_default_python_min_value(section):
    new_line = '{% set python_min = python_min|default("0.1a0") %}'
    if section[0].endswith("\n"):
        new_line += "\n"
        extra_space = "\n"
    else:
        extra_space = ""
    add_it = True
    for line in section:
        if "{% set python_min = " in line:
            add_it = False
            break

    if add_it:
        if "{% " not in section[0]:
            return [new_line, extra_space] + section
        else:
            return [new_line] + section
    else:
        return section


def _process_section(section, force_noarch_python=False, force_apply=False):
    if (not _has_noarch_python(section)) and (not force_noarch_python):
        return section

    found_it, section = _process_req_list(
        section, "host", "{{ python_min }}.*", force_apply=force_apply
    )
    logger.debug("applied `noarch: python` host? %s", found_it)
    found_it, section = _process_req_list(
        section, "run", ">={{ python_min }}", force_apply=force_apply
    )
    logger.debug("applied `noarch: python` to run? %s", found_it)
    found_it, section = _process_req_list(
        section,
        "requires",
        "={{ python_min }}",
        force_apply=force_apply,
    )
    logger.debug("applied `noarch: python` to test.requires? %s", found_it)
    if not found_it and force_apply:
        section = _add_test_requires(section)

    return section


def _apply_noarch_python_min(
    recipe_dir: str,
    attrs: "AttrsTypedDict",
    preserve_existing_specs: bool = True,
) -> None:
    fname = os.path.join(recipe_dir, "meta.yaml")
    if os.path.exists(fname):
        with open(fname) as fp:
            lines = fp.readlines()

        new_lines = []
        sections = _slice_into_output_sections(lines, attrs)
        if any(_has_noarch_python(section) for section in sections.values()):
            sections[-1] = _add_default_python_min_value(sections[-1])
        output_indices = sorted(list(sections.keys()))
        has_global_noarch_python = _has_noarch_python(sections[-1])
        for output_index in output_indices:
            section = sections[output_index]
            has_build_override = _has_build_section(section) and (output_index != -1)
            # _process_section returns list of lines already
            new_lines += _process_section(
                section,
                force_noarch_python=has_global_noarch_python
                and (not has_build_override),
                force_apply=not preserve_existing_specs,
            )

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
            piggy_back_migrations=[NoarchPythonMinCleanup(force=True)]
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
