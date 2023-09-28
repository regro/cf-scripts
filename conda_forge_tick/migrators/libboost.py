from conda_forge_tick.migrators.core import MiniMigrator
import os
import re


def _slice_into_output_sections(meta_yaml_lines, attrs):
    """
    Turn a recipe into slices corresponding to the outputs.

    To correctly process requirement sections from either
    single or multi-output recipes, we need to be able to
    restrict which lines we're operating on.

    Takes a list of lines and returns a dict from each output name to
    the list of lines where this output is described in the meta.yaml.
    The result will always contain a "global" section (== everything
    if there are no other outputs).
    """
    outputs = attrs["meta_yaml"].get("outputs", [])
    output_names = [o["name"] for o in outputs]
    # if there are no outputs, there's only one section
    if not output_names:
        return {"global": meta_yaml_lines}
    # output_names may contain duplicates; remove them but keep order
    names = []
    [names := names + [x] for x in output_names if x not in names]
    num_outputs = len(names)
    # add dummy for later use & reverse list for easier pop()ing
    names += ["dummy"]
    names.reverse()
    # initialize
    pos, prev, seek = 0, "global", names.pop()
    sections = {}
    for i, line in enumerate(meta_yaml_lines):
        # assumes order of names matches their appearance in meta_yaml,
        # and that they appear literally (i.e. no {{...}}) and without quotes
        if f"- name: {seek}" in line:
            # found the beginning of the next output;
            # everything until here belongs to the previous one
            sections[prev] = meta_yaml_lines[pos:i]
            # update
            pos, prev, seek = i, seek, names.pop()
            if seek == "dummy":
                # reached the last output; it goes until the end of the file
                sections[prev] = meta_yaml_lines[pos:]
    if len(sections) != num_outputs + 1:
        raise RuntimeError("Could not find all output sections in meta.yaml!")
    return sections


def _process_section(name, attrs, lines):
    """
    Migrate requirements per section.

    We want to migrate as follows:
    - rename boost to libboost-python
    - if boost-cpp is only a host-dep, rename to libboost-headers
    - if boost-cpp is _also_ a run-dep, rename it to libboost in host
      and remove it in run.
    """
    outputs = attrs["meta_yaml"].get("outputs", [])
    if name == "global":
        reqs = attrs["meta_yaml"].get("requirements", {})
    else:
        filtered = [o for o in outputs if o["name"] == name]
        if len(filtered) == 0:
            raise RuntimeError(f"Could not find output {name}!")
        reqs = filtered[0].get("requirements", {})

    build_req = reqs.get("build", set()) or set()
    host_req = reqs.get("host", set()) or set()
    run_req = reqs.get("run", set()) or set()

    is_boost_in_build = "boost-cpp" in build_req
    is_boost_in_host = "boost-cpp" in host_req
    is_boost_in_run = "boost-cpp" in run_req

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
    elif is_boost_in_host and name == "global" and outputs:
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
    """
    Replaces one pattern with a string in a set of lines, up to max_times
    """
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
        return not bool({"boost", "boost-cpp"} & all_req)

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
