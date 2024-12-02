import os
import subprocess

from conda_forge_tick.migrators.core import MiniMigrator
from conda_forge_tick.os_utils import pushd

MPIS = ["mpich", "openmpi"]


def _parse_cbc_mpi(lines):
    in_prab = False
    prab_indent: int | None = None
    mpi_indent: int | None = None
    new_lines = []
    for _line in lines:
        if _line.endswith("\n"):
            _line = _line[:-1]
        line = _line.split("#", 1)[0]

        if len(line.strip()) > 0:
            if "\t" in line:
                line = line.replace("\t", "    ")

            curr_indent = len(line) - len(line.lstrip())

            if "pin_run_as_build:" == line.strip():
                in_prab = True
                prab_indent = len(line) - len(line.lstrip())
            elif in_prab:
                if mpi_indent is not None:
                    if curr_indent > mpi_indent:
                        continue
                    else:
                        mpi_indent = None

                if mpi_indent is None:
                    for mpi in MPIS:
                        if mpi == line.split(":", 1)[0].strip():
                            mpi_indent = len(line) - len(line.lstrip())
                            break

                    if mpi_indent is not None:
                        continue

                if prab_indent is not None and curr_indent <= prab_indent:
                    in_prab = False
                    prab_indent = None

        new_lines.append(_line)

    iprab = None
    for i, ln in enumerate(new_lines):
        if "pin_run_as_build" in ln:
            iprab = i
            break
    if iprab is not None:
        prab_indent = len(new_lines[iprab]) - len(new_lines[iprab].lstrip())
        inext = None
        if iprab < len(new_lines) - 1:
            for i in range(iprab + 1, len(new_lines)):
                if len(new_lines[i].split("#", 1)[0].strip()) > 0:
                    inext = i
                    break

        if inext is not None:
            next_prab_indent = len(new_lines[inext]) - len(new_lines[inext].lstrip())
        else:
            next_prab_indent = prab_indent

        if prab_indent == next_prab_indent:
            new_lines.pop(iprab)

    return new_lines


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
            with open(fname) as fp:
                lines = fp.readlines()

            new_lines = _parse_cbc_mpi(lines)
            if len(new_lines) > 0:
                with open(fname, "w") as fp:
                    fp.write("\n".join(new_lines))
                    if new_lines[-1]:
                        # ensure trailing newline
                        fp.write("\n")
            else:
                with pushd(recipe_dir):
                    subprocess.run(["rm", "-f", "conda_build_config.yaml"])
