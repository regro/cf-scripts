import os

from conda_forge_tick.migrators.core import MiniMigrator, skip_migrator_due_to_schema
from conda_forge_tick.recipe_parser import CondaMetaYAML, get_yaml_parser


class YAMLRoundTrip(MiniMigrator):
    allowed_schema_versions = (0, 1)

    def filter(self, attrs, not_bad_str_start=""):
        return skip_migrator_due_to_schema(attrs, self.allowed_schema_versions)

    def migrate(self, recipe_dir, attrs, **kwargs):
        fname = os.path.join(recipe_dir, "meta.yaml")
        if os.path.exists(fname):
            try:
                with open(fname) as f:
                    meta = CondaMetaYAML(f.read())
                with open(fname, "w") as f:
                    meta.dump(f)
            except Exception:
                pass

        fname = os.path.join(recipe_dir, "recipe.yaml")
        if os.path.exists(fname):
            yml = get_yaml_parser(typ="rt")
            try:
                with open(fname) as f:
                    data = yml.load(f)
                with open(fname, "w") as f:
                    yml.dump(data, f)
            except Exception:
                pass
