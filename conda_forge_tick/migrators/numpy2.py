import os
import re

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.migrators.libboost import _replacer, _slice_into_output_sections

# pin_compatible("numpy"...)
# ^   ^           ^
# p   c           n
raw_pat_pcn = r".*\{\{\s*pin_compatible\([\"\']numpy[\"\'].*"
pat_pcn = re.compile(raw_pat_pcn)


def _process_section(name, attrs, lines):
    """
    Migrate requirements per section.

    We want to migrate as follows:
    - remove all occurrences of `{{ pin_compatible("numpy",...) }}`;
      these will be taken care of henceforth by numpy's run-export
    """
    # _replacer take the raw pattern, not the compiled one
    lines = _replacer(lines, raw_pat_pcn, "")
    return lines


class Numpy2Migrator(MiniMigrator):
    def filter(self, attrs, not_bad_str_start=""):
        lines = attrs["raw_meta_yaml"].splitlines()
        has_pcn = any(pat_pcn.search(line) for line in lines)
        # filter() returns True if we _don't_ want to migrate
        return not (has_pcn)

    def migrate(self, recipe_dir, attrs, **kwargs):
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
