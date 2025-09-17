import os
import re

from conda_forge_tick.migrators.core import MiniMigrator, skip_migrator_due_to_schema


def _slice_into_output_sections(meta_yaml_lines: list[str], attrs):
    """
    Turn a recipe into slices corresponding to the outputs.

    To correctly process requirement sections from either
    single or multi-output recipes, we need to be able to
    restrict which lines we're operating on.

    Takes a list of lines and returns a dict from each output index to
    the list of lines where this output is described in the meta.yaml.
    The result will always contain an index -1 for the top-level section (
    == everything if there are no other outputs).

    Raises
    ------
    RuntimeError
        If the recipe contains list-style outputs, or if the number of
        sections found does not match the number of outputs.
    """
    outputs_token_pos = None
    re_output_start = None
    re_outputs_token = re.compile(r"^\s*outputs:.*")
    re_outputs_token_list = re.compile(r"^\s*outputs:\s*\[.*")
    re_match_block_list = re.compile(r"^\s*\-.*")

    pos = 0
    section_index = -1
    sections = {}
    for i, line in enumerate(meta_yaml_lines):
        # we go through lines until we find the `outputs:` line
        # we grab its position for later
        if re_outputs_token.match(line) and outputs_token_pos is None:
            # we cannot handle list-style outputs so raise an error
            if re_outputs_token_list.match(line):
                raise RuntimeError(
                    "List-style outputs not supported for outputs slicing!"
                )

            outputs_token_pos = i
            continue

        # next we need to find the indent of the first output list element.
        # it could be anything from the indent of the `outputs:` line to that number
        # plus zero or more spaces. Typically, the indent is the same as the `outputs:`
        # plus one of [0, 2, 4] spaces.
        # once we find the first output list element, we build a regex to match any list
        # element at that indent level.
        if (
            outputs_token_pos is not None
            and re_output_start is None
            and i > outputs_token_pos
            and re_match_block_list.match(line)
        ):
            outputs_indent = len(line) - len(line.lstrip())
            re_output_start = re.compile(r"^" + r" " * outputs_indent + r"-.*")

        # finally we add slices for each output section as we find list elements at
        # the correct indent level
        # this block adds the previous output when it finds the start of the next one
        if (
            outputs_token_pos is not None
            and re_output_start is not None
            and re_output_start.match(line)
        ):
            sections[section_index] = meta_yaml_lines[pos:i]
            section_index += 1
            pos = i
            continue

    # the last output needs to be added
    sections[section_index] = meta_yaml_lines[pos:]

    # finally, if a block list at the same indent happens after the outputs section ends
    # we'll have extra outputs that are not real. We remove them
    # by checking if there is a name key in the dict
    re_name = re.compile(r"^\s*(-\s+)?name:.*")
    final_sections = {}
    final_sections[-1] = sections[-1]  # we always keep the first global section
    final_output_index = 0
    carried_lines: list[str] = []
    for output_index in range(len(sections) - 1):
        section = sections[output_index]
        if any(re_name.match(line) for line in section):
            # we found another valid output so we add any carried lines to the previous output
            if carried_lines:
                final_sections[final_output_index - 1] += carried_lines
                carried_lines = []

            # add the next valid output
            final_sections[final_output_index] = section
            final_output_index += 1
        else:
            carried_lines += section

    # make sure to add any trailing carried lines to the last output we found
    if carried_lines:
        final_sections[final_output_index - 1] += carried_lines

    # double check length here to flag possible weird cases
    # this check will fail incorrectly for outputs with the same name
    # but different build strings.
    outputs = attrs["meta_yaml"].get("outputs", [])
    outputs = {o["name"] for o in outputs}
    if len(final_sections) != len(outputs) + 1:
        raise RuntimeError(
            f"Could not find all output sections in meta.yaml! "
            f"Found {len(final_sections)} sections for outputs names = {outputs}.",
        )

    return final_sections


def _process_section(output_index, attrs, lines):
    """
    Migrate requirements per section.

    We want to migrate as follows:
    - rename boost to libboost-python
    - if boost-cpp is only a host-dep, rename to libboost-headers
    - if boost-cpp is _also_ a run-dep, rename it to libboost in host
      and remove it in run.

    Raises
    ------
    RuntimeError
        If the output given by output_index cannot be found in attrs.
    """
    outputs = attrs["meta_yaml"].get("outputs", [])
    if output_index == -1:
        reqs = attrs["meta_yaml"].get("requirements", {})
    else:
        seen_names = set()
        unique_outputs = []
        for output in outputs:
            _name = output["name"]
            if _name in seen_names:
                continue
            seen_names.add(_name)
            unique_outputs.append(output)

        try:
            reqs = unique_outputs[output_index].get("requirements", {})
        except IndexError:
            raise RuntimeError(f"Could not find output {output_index}!")

    build_req = reqs.get("build", set()) or set()
    host_req = reqs.get("host", set()) or set()
    run_req = reqs.get("run", set()) or set()

    is_boost_in_build = any((x or "").startswith("boost-cpp") for x in build_req)
    is_boost_in_host = any((x or "").startswith("boost-cpp") for x in host_req)
    is_boost_in_run = any((x or "").startswith("boost-cpp") for x in run_req)

    # anything behind a comment needs to get replaced first, so it
    # doesn't mess up the counts below
    lines = _replacer(
        lines,
        r"^(?P<before>\s*\#.*)\b(boost-cpp)\b(?P<after>.*)$",
        r"\g<before>libboost-devel\g<after>",
    )

    # boost-cpp, followed optionally by e.g. " =1.72.0" or " {{ boost_cpp }}"
    p_base = r"boost-cpp(\s*[<>=]?=?[\d\.]+)?(\s+\{\{.*\}\})?"
    p_selector = r"(\s+\#\s\[.*\])?"
    if is_boost_in_build:
        # if boost also occurs in build (assuming only once), replace it once
        # but keep selectors (e.g. `# [build_platform != target_platform]`)
        lines = _replacer(lines, p_base, "libboost-devel", max_times=1)

    if is_boost_in_host and is_boost_in_run:
        # presence in both means we want to replace with libboost, but only in host;
        # because libboost-devel only exists from newest 1.82, we remove version pins;
        # generally we assume there's one occurrence in host and on in run, but due
        # to selectors, this may not be the case; to keep the logic tractable, we
        # remove all occurrences but the first (and thus need to remove selectors too)
        lines = _replacer(lines, p_base + p_selector, "libboost-devel", max_times=1)
        # delete all other occurrences
        lines = _replacer(lines, "boost-cpp", "")
    elif is_boost_in_host and output_index == -1 and outputs:
        # global build section for multi-output with no run-requirements;
        # safer to use the full library here
        lines = _replacer(lines, p_base + p_selector, "libboost-devel", max_times=1)
        # delete all other occurrences
        lines = _replacer(lines, "boost-cpp", "")
    elif is_boost_in_host:
        # here we know we can replace all with libboost-headers
        lines = _replacer(lines, p_base, "libboost-headers")
    elif is_boost_in_run and outputs:
        # case of multi-output but with the host deps being only in
        # global section; remove run-deps of boost-cpp nevertheless
        lines = _replacer(lines, "boost-cpp", "")
    # in any case, replace occurrences of "- boost"
    lines = _replacer(lines, "- boost", "- libboost-python-devel")
    lines = _replacer(lines, r"pin_compatible\([\"\']boost", "")
    return lines


def _replacer(lines, from_this, to_that, max_times=None):
    """Replace one pattern with a string in a set of lines, up to max_times."""
    i = 0
    new_lines = []
    pat = re.compile(from_this)
    for line in lines:
        if pat.search(line) and (max_times is None or i < max_times):
            i += 1
            # if to_that is empty, discard line
            if not to_that:
                continue
            line = pat.sub(to_that, line)
        new_lines.append(line)
    return new_lines


class LibboostMigrator(MiniMigrator):
    def filter(self, attrs, not_bad_str_start=""):
        host_req = (attrs.get("requirements", {}) or {}).get("host", set()) or set()
        run_req = (attrs.get("requirements", {}) or {}).get("run", set()) or set()
        all_req = set(host_req) | set(run_req)
        # filter() returns True if we _don't_ want to migrate
        return (
            not bool({"boost", "boost-cpp"} & all_req)
        ) or skip_migrator_due_to_schema(attrs, self.allowed_schema_versions)

    def migrate(self, recipe_dir, attrs, **kwargs):
        fname = os.path.join(recipe_dir, "meta.yaml")
        if os.path.exists(fname):
            with open(fname) as fp:
                lines = fp.readlines()

            new_lines = []
            sections = _slice_into_output_sections(lines, attrs)
            for output_index, section in sections.items():
                # _process_section returns list of lines already
                new_lines += _process_section(output_index, attrs, section)

            with open(fname, "w") as fp:
                fp.write("".join(new_lines))
