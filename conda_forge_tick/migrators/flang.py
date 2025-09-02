import os
import re

from conda_forge_tick.migrators.core import MiniMigrator, skip_migrator_due_to_schema
from conda_forge_tick.migrators.libboost import _replacer, _slice_into_output_sections

# compiler("m2w64_fortran")
#           ^^    ^
#           m2    f
raw_pat_m2f = r"^(?P<indent>\s*)- \{\{\s*compiler\([\"\']m2w64_fortran.*"
pat_m2f = re.compile(raw_pat_m2f)

# fortran, but with a selector
raw_pat_fws = (
    r"^(?P<indent>\s*)- \{\{\s*compiler\([\"\']fortran[\"\']\)\s*\}\}\s*\# \[.*"
)
pat_fws = re.compile(raw_pat_fws)

# a compiler OR a comment
raw_pat_comp = r".*\{\{\s*(compiler|stdlib)\([\"\'](?:m2w64_)?(?P<lang>c(?:xx)?|fortran)\W.*|\s*\#.*"
pat_comp = re.compile(raw_pat_comp)


def _process_section(lines):
    """
    Migrate requirements per section.

    We want to migrate as follows:
    - find if there's a `{{ compiler("m2w64_fortran") }}` in a section
    - if so, find all the surrounding lines that are a compiler or stdlib jinja
    - determine the compiler languages (modulo `m2w64_`)
    - write a selector-less compiler block with stdlib and all the right languages
    """
    # the below does not apply if there's no `{{ compiler("m2w64_fortran") }}`
    if not any(pat_m2f.match(x) for x in lines):
        return lines

    # `c_` stands for compilers (and comments)
    c_bools = [(i, pat_comp.match(x)) for i, x in enumerate(lines)]
    c_lines = [i for i, is_comp in c_bools if is_comp]
    # extend in both directions so we can take forward and backward differences;
    # -2 is so that `diff > 1` below will be true even if there's a comment in
    # the very first line; needed to get matching number of block beginnings/ends.
    c_lines_ext = [-2] + c_lines + [len(lines)]
    c_fw_diff = [(i, i_next - i) for i, i_next in zip(c_lines, c_lines_ext[2:])]
    c_bw_diff = [(i, i - i_prev) for i, i_prev in zip(c_lines, c_lines_ext[:-2])]
    c_end = [i for i, diff in c_fw_diff if diff > 1]
    c_begin = [i for i, diff in c_bw_diff if diff > 1]

    m2f_line = [i for i, x in enumerate(lines) if pat_m2f.match(x)][0]
    indent = pat_m2f.sub(r"\g<indent>", lines[m2f_line])
    begin, end = [(b, e) for b, e in zip(c_begin, c_end) if b <= m2f_line <= e][0]

    langs = {pat_comp.sub(r"\g<lang>", x) for x in lines[begin : end + 1]}
    # if we caught a comment, lang will be ""
    langs_list = sorted([x for x in langs if x])
    comp_block_new = [f'{indent}- {{{{ compiler("{lang}") }}}}' for lang in langs_list]
    comp_block_new = [f'{indent}- {{{{ stdlib("c") }}}}'] + comp_block_new

    new_lines = lines[:begin] + comp_block_new + lines[end + 1 :]
    return new_lines


class FlangMigrator(MiniMigrator):
    def filter(self, attrs, not_bad_str_start=""):
        lines = attrs["raw_meta_yaml"].splitlines()
        has_m2f = any(pat_m2f.search(line) or pat_fws.search(line) for line in lines)
        # filter() returns True if we _don't_ want to migrate
        return (not (has_m2f)) or skip_migrator_due_to_schema(
            attrs, self.allowed_schema_versions
        )

    def migrate(self, recipe_dir, attrs, **kwargs):
        fname = os.path.join(recipe_dir, "meta.yaml")
        if os.path.exists(fname):
            with open(fname) as fp:
                # strip trailing newlines, because it breaks regex processing
                lines = [x.rstrip() for x in fp.readlines()]

            new_lines = []
            sections = _slice_into_output_sections(lines, attrs)
            for section in sections.values():
                # _process_section returns list of lines already
                new_lines += _process_section(section)

            # for non-m2w64 compilers, remove selectors from `{{ compiler("fortran") }}`
            new_lines = _replacer(
                new_lines, raw_pat_fws, r'\g<indent>- {{ compiler("fortran") }}'
            )

            # remove some obsolete outputs
            new_lines = _replacer(new_lines, r"- flang.*", "")
            new_lines = _replacer(new_lines, r"- vs2019_win-64.*", "")
            new_lines = _replacer(new_lines, r"- m2w64-gcc-(lib)?gfortran.*", "")

            with open(fname, "w") as fp:
                fp.write("\n".join(new_lines))
