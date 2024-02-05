import os
import re

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.migrators.libboost import _slice_into_output_sections

pat_stub = re.compile(r"(c|cxx|fortran)_compiler_stub")
pat_compiler = re.compile(
    r"(?P<indent>\s*)-\s*"
    r"(?P<compiler>\{\{\s*compiler\([\"\'](c|cxx|fortran)[\"\']\)\s*\}\})"
    r"\s*(?P<selector>\#\s+\[[\w\s]+\])?"
)
pat_stdlib = re.compile(r".*\{\{\s*stdlib\([\"\']c[\"\']\)\s*\}\}.*")


def _process_section(name, attrs, lines):
    """
    Migrate requirements per section.

    We want to migrate as follows:
    - if there's _any_ `{{ stdlib("c") }}` in the recipe, abort (consider it migrated)
    - if there's `{{ compiler("c") }}` in build, add `{{ stdlib("c") }}` in host
    - where there's no host-section, add it
    """
    outputs = attrs["meta_yaml"].get("outputs", [])
    global_reqs = attrs["meta_yaml"].get("requirements", {})
    if name == "global":
        reqs = global_reqs
    else:
        filtered = [o for o in outputs if o["name"] == name]
        if len(filtered) == 0:
            raise RuntimeError(f"Could not find output {name}!")
        reqs = filtered[0].get("requirements", {})

    build_reqs = reqs.get("build", set()) or set()
    global_build_reqs = global_reqs.get("build", set()) or set()

    # either there's a compiler in the output we're processing, or the
    # current output has no build-section but relies on the global one
    needs_stdlib = any(pat_stub.search(x or "") for x in build_reqs)
    needs_stdlib |= not bool(build_reqs) and any(
        pat_stub.search(x or "") for x in global_build_reqs
    )

    if not needs_stdlib:
        # no change
        return lines

    line_build = line_compiler = line_host = line_run = line_constrain = line_test = 0
    indent = selector = ""
    for i, line in enumerate(lines):
        if re.match(r".*build:.*", line):
            # always update this, as requirements.build follows build.{number,...}
            line_build = i
        elif pat_compiler.search(line):
            line_compiler = i
            indent = pat_compiler.match(line).group("indent")
            selector = pat_compiler.match(line).group("selector") or ""
        elif re.match(r".*host:.*", line):
            line_host = i
        elif re.match(r".*run:.*", line):
            line_run = i
        elif re.match(r".*run_constrained:.*", line):
            line_constrain = i
        elif re.match(r".*test:.*", line):
            line_test = i
            # ensure we don't read past test section (may contain unrelated deps)
            break

    if indent == "":
        # no compiler in current output; take first line of section as reference (without last \n);
        # ensure it works for both global build section as well as for `- name: <output>`.
        indent = (
            re.sub(r"^([\s\-]*).*", r"\1", lines[0][:-1]).replace("-", " ") + " " * 4
        )

    to_insert = indent + '- {{ stdlib("c") }}' + selector + "\n"
    if line_host == 0:
        # no host section, need to add it
        to_insert = indent[:-2] + "host:\n" + to_insert

    if line_host == 0 and line_run == 0:
        # neither host nor run section; insert before
        # run_constrained (if it exists) else test section
        line_insert = line_constrain or line_test
        if not line_insert:
            raise RuntimeError("Don't know where to insert host section!")
    elif line_host == 0:
        # no host section, insert before run
        line_insert = line_run
    else:
        # by default, we insert as first host dependency
        line_insert = line_host + 1

    return lines[:line_insert] + [to_insert] + lines[line_insert:]


class StdlibMigrator(MiniMigrator):
    def filter(self, attrs, not_bad_str_start=""):
        lines = attrs["raw_meta_yaml"].splitlines()
        already_migrated = any(pat_stdlib.search(line) for line in lines)
        has_compiler = any(pat_compiler.search(line) for line in lines)
        # filter() returns True if we _don't_ want to migrate
        return already_migrated or not has_compiler

    def migrate(self, recipe_dir, attrs, **kwargs):
        outputs = attrs["meta_yaml"].get("outputs", [])

        fname = os.path.join(recipe_dir, "meta.yaml")
        if os.path.exists(fname):
            with open(fname) as fp:
                lines = fp.readlines()

            new_lines = []
            sections = _slice_into_output_sections(lines, attrs)
            for name, section in sections.items():
                # _process_section returns list of lines already
                new_lines += _process_section(name, attrs, section)

            with open(fname, "w") as fp:
                fp.write("".join(new_lines))
