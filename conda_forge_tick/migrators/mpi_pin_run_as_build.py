import os
import subprocess

from ruamel.yaml import YAML

from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.migrators.core import MiniMigrator

MPIS = ["mpich", "openmpi"]


class MPIPinRunAsBuildCleanup(MiniMigrator):
    def filter(self, attrs, not_bad_str_start=""):
        host_req = (attrs.get("requirements", {}) or {}).get("host", set()) or set()

        if any(mpi in host_req for mpi in MPIS):
            return False
        else:
            return True

    def migrate(self, recipe_dir, attrs, **kwargs):
        fname = os.path.join(recipe_dir, "conda_build_config.yaml")
        if os.path.exists(fname):
            parser = YAML(typ="rt")
            parser.indent(mapping=2, sequence=4, offset=2)
            parser.width = 320

            with open(fname) as fp:
                cbc = parser.load(fp.read())

            if "pin_run_as_build" in cbc:
                for mpi in MPIS:
                    if mpi in cbc["pin_run_as_build"]:
                        del cbc["pin_run_as_build"][mpi]
                if len(cbc["pin_run_as_build"]) == 0:
                    del cbc["pin_run_as_build"]

            if len(cbc) > 0:
                with open(fname, "w") as fp:
                    parser.dump(cbc, stream=fp)
            else:
                with indir(recipe_dir):
                    subprocess.run("git rm -f conda_build_config.yaml", shell=True)
                    subprocess.run("rm -f conda_build_config.yaml", shell=True)
