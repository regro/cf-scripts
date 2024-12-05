import os
import re

from conda_forge_tick.migrators.core import MiniMigrator, skip_migrator_due_to_schema
from conda_forge_tick.migrators.libboost import _replacer

# pin_compatible("numpy"...)
# ^   ^           ^
# p   c           n
raw_pat_pcn = r".*\{\{\s*pin_compatible\([\"\']numpy[\"\'].*"
pat_pcn = re.compile(raw_pat_pcn)


class Numpy2Migrator(MiniMigrator):
    def filter(self, attrs, not_bad_str_start=""):
        lines = attrs["raw_meta_yaml"].splitlines()
        has_pcn = any(pat_pcn.search(line) for line in lines)
        # filter() returns True if we _don't_ want to migrate
        return (not (has_pcn)) or skip_migrator_due_to_schema(
            attrs, self.allowed_schema_versions
        )

    def migrate(self, recipe_dir, attrs, **kwargs):
        fname = os.path.join(recipe_dir, "meta.yaml")
        if os.path.exists(fname):
            with open(fname) as fp:
                lines = fp.readlines()

            # _replacer take the raw pattern, not the compiled one
            new_lines = _replacer(lines, raw_pat_pcn, "")

            with open(fname, "w") as fp:
                fp.write("".join(new_lines))
