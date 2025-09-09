import logging
import os
import re
import subprocess
import tempfile
import typing
from typing import Any

from conda_forge_tick.migrators.core import MiniMigrator, skip_migrator_due_to_schema
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.provide_source_code import provide_source_code
from conda_forge_tick.recipe_parser import CondaMetaYAML

try:
    from conda_smithy.lint_recipe import NEEDED_FAMILIES
except ImportError:
    NEEDED_FAMILIES = ["gpl", "bsd", "mit", "apache", "psf", "agpl", "lgpl"]

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

LICENSE_SPLIT = re.compile(r"\||\+")

logger = logging.getLogger(__name__)


def replace_in_file(pattern, new, fname, leading_whitespace=True):
    """Replace a given pattern in a file. If leading whitespace is True,
    whitespace at the beginning of a line will be captured and preserved.
    Otherwise, the pattern itself must contain all leading whitespace.

    This function is vendored from rever under their license:

    BSD 3-Clause License

    Copyright (c) 2017, Anthony Scopatz
    Copyright (c) 2018, The Regro Developers
    All rights reserved.

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright notice, this
    list of conditions and the following disclaimer.

    * Redistributions in binary form must reproduce the above copyright notice,
    this list of conditions and the following disclaimer in the documentation
    and/or other materials provided with the distribution.

    * Neither the name of the copyright holder nor the names of its
    contributors may be used to endorse or promote products derived from
    this software without specific prior written permission.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
    AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
    IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
    DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
    FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
    DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
    SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
    CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
    OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
    OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
    """
    with open(fname) as f:
        raw = f.read()
    lines = raw.splitlines()
    if leading_whitespace:
        ptn = re.compile(r"(\s*?)" + pattern)
    else:
        ptn = re.compile(pattern)
    for i, line in enumerate(lines):
        m = ptn.match(line)
        if m is not None:
            lines[i] = m.group(1) + new if leading_whitespace else new
    upd = "\n".join(lines) + "\n"
    with open(fname, "w") as f:
        f.write(upd)


def _to_spdx(lic):
    """
    We are munging this stuff from conda-build.

    d_license = {'agpl3': ['AGPL-3', 'AGPL (>= 3)', 'AGPL',
                           'GNU Affero General Public License'],
                 'artistic2': ['Artistic-2.0', 'Artistic License 2.0'],
                 'gpl2': ['GPL-2', 'GPL (>= 2)', 'GNU General Public License (>= 2)'],
                 'gpl3': ['GPL-3', 'GPL (>= 3)', 'GNU General Public License (>= 3)',
                          'GPL', 'GNU General Public License'],
                 'lgpl2': ['LGPL-2', 'LGPL (>= 2)'],
                 'lgpl21': ['LGPL-2.1', 'LGPL (>= 2.1)'],
                 'lgpl3': ['LGPL-3', 'LGPL (>= 3)', 'LGPL',
                           'GNU Lesser General Public License'],
                 'bsd2': ['BSD_2_clause', 'BSD_2_Clause', 'BSD 2-clause License'],
                 'bsd3': ['BSD_3_clause', 'BSD_3_Clause', 'BSD 3-clause License'],
                 'mit': ['MIT'],
                 }
    """
    r_to_spdx = {
        "AGPL-3": "AGPL-3.0-only",
        "AGPL (>= 3)": "AGPL-3.0-or-later",
        "Artistic License 2.0": "Artistic-2.0",
        "GPL-2": "GPL-2.0-only",
        "GPL (>= 2)": "GPL-2.0-or-later",
        "GNU General Public License (>= 2)": "GPL-2.0-or-later",
        "GPL-3": "GPL-3.0-only",
        "GPL (>= 3)": "GPL-3.0-or-later",
        "GNU General Public License (>= 3)": "GPL-3.0-or-later",
        "LGPL-2": "LGPL-2.0-only",
        "LGPL (>= 2)": "LGPL-2.0-or-later",
        "LGPL-2.1": "LGPL-2.1-only",
        "LGPL (>= 2.1)": "LGPL-2.1-or-later",
        "LGPL-3": "LGPL-3.0-only",
        "LGPL (>= 3)": "LGPL-3.0-or-later",
        "BSD_2_clause": "BSD-2-Clause",
        "BSD_2_Clause": "BSD-2-Clause",
        "BSD 2-clause License": "BSD-2-Clause",
        "BSD_3_clause": "BSD-3-Clause",
        "BSD_3_Clause": "BSD-3-Clause",
        "BSD 3-clause License": "BSD-3-Clause",
        "Apache License 2.0": "Apache-2.0",
        "CC BY-SA 4.0": "CC-BY-SA-4.0",
        "Apache License (== 2.0)": "Apache-2.0",
        "FreeBSD": "BSD-2-Clause-FreeBSD",
        "Apache License (>= 2.0)": "Apache-2.0",
        "CC0": "CC0-1.0",
        "MIT License": "MIT",
        "CeCILL-2": "CECILL-2.0",
        "CC BY-NC-SA 4.0": "CC-BY-NC-SA-4.0",
        "CC BY 4.0": "CC-BY-4.0",
    }
    return r_to_spdx.get(lic, lic)


def _remove_file_refs(_parts):
    _p = []
    for p in _parts:
        if p.strip().startswith("file "):
            pass
        else:
            _p.append(p)
    return _p


def _munge_licenses(lparts):
    new_lparts = []
    for lpart in lparts:
        if " | " in lpart:
            _parts = _remove_file_refs(lpart.split(" | "))
            last = len(_parts) - 1
            for i, _p in enumerate(_parts):
                _p = _munge_licenses([_p])
                if len(_p) > 1:
                    new_lparts.append("(")
                new_lparts.extend(_p)
                if len(_p) > 1:
                    new_lparts.append(")")

                if i != last:
                    new_lparts.append(" OR ")

        elif " + " in lpart:
            _parts = _remove_file_refs(lpart.split(" + "))
            last = len(_parts) - 1
            for i, _p in enumerate(_parts):
                _p = _munge_licenses([_p])
                if len(_p) > 1:
                    new_lparts.append("(")
                new_lparts.extend(_p)
                if len(_p) > 1:
                    new_lparts.append(")")

                if i != last:
                    new_lparts.append(" AND ")
        else:
            new_lparts.append(_to_spdx(lpart.strip()))
    return new_lparts


def _scrape_license_string(pkg):
    d: dict[str, str | list[str] | None] = {}

    if pkg.startswith("r-"):
        pkg = pkg[2:]

    logger.info("LICENSE running cran skeleton for pkg %s", pkg)

    with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
        subprocess.run(
            [
                "conda",
                "skeleton",
                "cran",
                "--allow-archived",
                "--use-noarch-generic",
                pkg,
            ],
            check=True,
        )
        with open("r-%s/meta.yaml" % pkg) as fp:
            in_about = False
            meta_yaml = []
            for line in fp.readlines():
                if line.startswith("about:"):
                    in_about = True
                elif line.startswith("extra:"):
                    in_about = False

                if in_about:
                    meta_yaml.append(line)

                if line.startswith("# License:"):
                    d["cran_license"] = line[len("# License:") :].strip()

    cmeta = CondaMetaYAML("".join(meta_yaml))

    d["license_file"] = [
        lf for lf in cmeta.meta.get("about", {}).get("license_file", [])
    ]
    if len(d["license_file"]) == 0:  # type: ignore[arg-type] # this is not a typed dict
        d["license_file"] = None

    if "cran_license" in d:
        spdx = _munge_licenses([d["cran_license"]])
        if "(Restricts use)" in cmeta.meta.get("about", {}).get("license", ""):
            if len(spdx) > 1:
                spdx = ["("] + spdx + [")", " AND ", "LicenseRef-RestrictsUse"]
            else:
                spdx = spdx + [" AND ", "LicenseRef-RestrictsUse"]
        d["spdx_license"] = "".join(spdx)

    else:
        d["spdx_license"] = None

    if d:
        return d
    else:
        return None


def _do_r_license_munging(pkg, recipe_dir):
    try:
        d = _scrape_license_string(pkg)
        logger.info("LICENSE R package license data: %s", d)

        with open(os.path.join(recipe_dir, "meta.yaml")) as fp:
            cmeta = CondaMetaYAML(fp.read())

        if d["license_file"] is not None:
            cmeta.meta["about"]["license_file"] = d["license_file"]

        if d["spdx_license"] is not None:
            cmeta.meta["about"]["license"] = d["spdx_license"]
        elif d["cran_license"] is not None:
            cmeta.meta["about"]["license"] = d["cran_license"]

        with open(os.path.join(recipe_dir, "meta.yaml"), "w") as fp:
            cmeta.dump(fp)

    except Exception as e:
        logger.info("LICENSE R license ERROR: %s", repr(e))
        pass


def _is_r(attrs):
    if (
        attrs.get("feedstock_name", "").startswith("r-")
        or attrs.get("name", "").startswith("r-")
    ) and (
        "r-base" in attrs.get("raw_meta_yaml", "")
        or "r-base" in attrs.get("requirements", {}).get("run", set())
    ):
        return True
    else:
        return False


class LicenseMigrator(MiniMigrator):
    post_migration = True

    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        license = attrs.get("meta_yaml", {}).get("about", {}).get("license", "")
        license_fam = (
            attrs.get("meta_yaml", {})
            .get("about", {})
            .get("license_family", "")
            .lower()
            or license.lower().partition("-")[0].partition("v")[0].partition(" ")[0]
        )
        if (
            license_fam in NEEDED_FAMILIES
            or any(n in license_fam for n in NEEDED_FAMILIES)
            or _is_r(attrs)
        ) and "license_file" not in attrs.get("meta_yaml", {}).get("about", {}):
            return False or skip_migrator_due_to_schema(
                attrs, self.allowed_schema_versions
            )
        return True

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        # r- recipes have a special syntax here
        if (
            attrs.get("feedstock_name", "").startswith("r-")
            or attrs.get("name", "").startswith("r-")
        ) and "r-base" in attrs["raw_meta_yaml"]:
            if attrs.get("feedstock_name", None) is not None:
                if attrs.get("feedstock_name", None).endswith("-feedstock"):  # type: ignore[union-attr] # this is not a typed dict
                    name = attrs.get("feedstock_name")[: -len("-feedstock")]  # type: ignore[arg-type,index] # this is not a typed dict
                else:
                    name = attrs.get("feedstock_name")
            else:
                name = attrs.get("name", None)
            _do_r_license_munging(name, recipe_dir)
            return

        try:
            with provide_source_code(recipe_dir) as cb_work_dir:
                if cb_work_dir is None:
                    return
                with pushd(cb_work_dir):
                    # look for a license file
                    license_files = [
                        s
                        for s in os.listdir(".")
                        if any(
                            s.lower().startswith(k)
                            for k in ["license", "copying", "copyright"]
                        )
                    ]

                # if there is a license file in tarball update things
                if license_files:
                    with pushd(recipe_dir):
                        """BSD 3-Clause License
                        Copyright (c) 2017, Anthony Scopatz
                        Copyright (c) 2018, The Regro Developers
                        All rights reserved."""
                        with open("meta.yaml") as f:
                            raw = f.read()
                        lines = raw.splitlines()
                        ptn = re.compile(r"(\s*?)" + "license:")
                        for i, line in enumerate(lines):
                            m = ptn.match(line)
                            if m is not None:
                                break
                        # TODO: Sketchy type assertion
                        assert m is not None
                        ws = m.group(1)
                        if len(license_files) == 1:
                            replace_in_file(
                                line,
                                line
                                + "\n"
                                + ws
                                + f"license_file: {list(license_files)[0]}",
                                "meta.yaml",
                            )
                        else:
                            # note that this white space is not perfect but works for
                            # most of the situations
                            replace_in_file(
                                line,
                                line
                                + "\n"
                                + ws
                                + "license_file: \n"
                                + "".join(f"{ws * 2}- {z} \n" for z in license_files),
                                "meta.yaml",
                            )

                # if license not in tarball do something!
                # check if github in dev url, then use that to get the license
        except Exception:
            return
