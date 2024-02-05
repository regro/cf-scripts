import os

from conda_forge_tick.migrators.core import MiniMigrator


def _parse_qt(lines):
    new_lines = []
    for line in lines:
        if line.endswith(" qt\n"):
            line = line.replace(" qt", " qt-main")
        line = line.replace(" qt ", " qt-main ")
        new_lines.append(line)
    return new_lines


class QtQtMainMigrator(MiniMigrator):
    def filter(self, attrs, not_bad_str_start=""):
        host_req = (attrs.get("requirements", {}) or {}).get("host", set()) or set()
        return "qt" not in host_req

    def migrate(self, recipe_dir, attrs, **kwargs):
        fname = os.path.join(recipe_dir, "meta.yaml")
        if os.path.exists(fname):
            with open(fname) as fp:
                lines = fp.readlines()

            new_lines = _parse_qt(lines)
            with open(fname, "w") as fp:
                fp.write("".join(new_lines))
