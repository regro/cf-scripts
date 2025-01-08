import os

from conda_forge_tick.migrators.core import MiniMigrator, skip_migrator_due_to_schema


def _parse_xz(lines):
    new_lines = []
    for line in lines:
        if line.endswith(" xz\n"):
            line = line.replace(" xz", " liblzma-devel")
        line = line.replace(" xz ", " liblzma-devel ")
        new_lines.append(line)
    return new_lines


class XzLibLzmaDevelMigrator(MiniMigrator):
    def filter(self, attrs, not_bad_str_start=""):
        host_req = (attrs.get("requirements", {}) or {}).get("host", set()) or set()
        return "xz" not in host_req or skip_migrator_due_to_schema(
            attrs, self.allowed_schema_versions
        )

    def migrate(self, recipe_dir, attrs, **kwargs):
        fname = os.path.join(recipe_dir, "meta.yaml")
        if os.path.exists(fname):
            with open(fname) as fp:
                lines = fp.readlines()

            new_lines = _parse_xz(lines)
            with open(fname, "w") as fp:
                fp.write("".join(new_lines))
