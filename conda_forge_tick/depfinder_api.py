# Copyright (c) <2015-2016>, Eric Dill
#
# All rights reserved.  Redistribution and use in source and binary forms, with
# or without modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors
# may be used to endorse or promote products derived from this software without
# specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import logging
from collections import defaultdict
from concurrent.futures._base import as_completed
from concurrent.futures.thread import ThreadPoolExecutor
from fnmatch import fnmatch

from depfinder.inspection import iterate_over_library
from depfinder.stdliblist import builtin_modules as _builtin_modules
from depfinder.utils import SKETCHY_TYPES_TABLE

from conda_forge_tick.import_to_pkg import extract_pkg_from_import

logger = logging.getLogger(__name__)


def recursively_search_for_name(name, module_names):
    while True:
        if name in module_names:
            return name
        else:
            if "." in name:
                name = name.rsplit(".", 1)[0]
            else:
                return False


def report_conda_forge_names_from_import_map(
    total_imports,
    builtin_modules=None,
    ignore=None,
):
    if ignore is None:
        ignore = []
    if builtin_modules is None:
        builtin_modules = _builtin_modules
    report_keys = [
        "required",
        "questionable",
        "builtin",
        "questionable no match",
        "required no match",
    ]
    report = {k: set() for k in report_keys}
    import_to_pkg = {k: {} for k in report_keys}
    futures = {}

    with ThreadPoolExecutor() as pool:
        for name, md in total_imports.items():
            if all(
                [
                    any(fnmatch(filename, ignore_element) for ignore_element in ignore)
                    for filename, _ in md
                ],
            ):
                continue
            elif recursively_search_for_name(name, builtin_modules):
                report["builtin"].add(name)
                continue
            future = pool.submit(extract_pkg_from_import, name)
            futures[future] = md
    for future in as_completed(futures):
        md = futures[future]
        most_likely_pkg, _import_to_pkg = future.result()

        for (filename, lineno), import_metadata in md.items():
            # Make certain to throw out imports, since an import can happen multiple times
            # under different situations, import matplotlib is required by a test file
            # but is questionable for a regular file
            if any(fnmatch(filename, ignore_element) for ignore_element in ignore):
                continue
            _name = list(_import_to_pkg.keys())[0]
            if any(import_metadata.get(v, False) for v in SKETCHY_TYPES_TABLE.values()):
                # if we couldn't find any artifacts to represent this then it doesn't exist in our maps
                if not _import_to_pkg[_name]:
                    report_key = "questionable no match"
                else:
                    report_key = "questionable"
            else:
                # if we couldn't find any artifacts to represent this then it doesn't exist in our maps
                if not _import_to_pkg[_name]:
                    report_key = "required no match"
                else:
                    report_key = "required"

            report[report_key].add(most_likely_pkg)
            import_to_pkg[report_key].update(_import_to_pkg)

    return report, import_to_pkg


def simple_import_to_pkg_map(
    path_to_source_code,
    builtins=None,
    ignore=None,
    custom_namespaces=None,
):
    """Provide the map between all the imports and their possible packages.

    Parameters
    ----------
    path_to_source_code : str
    builtins : list, optional
        List of python builtins to partition into their own section
    ignore : list, optional
        String pattern which if matched causes the file to not be inspected
    custom_namespaces : list of str or None
        If not None, then resulting package outputs will list everying under these
        namespaces (e.g., for packages foo.bar and foo.baz, the outputs are foo.bar
        and foo.baz instead of foo if custom_namespaces=["foo"]).

    Returns
    -------
    dict of dict of sets:
        The classes of requirements (required, questionable, builtin, no match required, no match questionable),
        name of the import and packages that provide that import
    """
    # run depfinder on source code
    if ignore is None:
        ignore = []
    total_imports_list = []
    for _, _, c in iterate_over_library(
        path_to_source_code,
        custom_namespaces=custom_namespaces,
    ):
        total_imports_list.append(c.total_imports)
    total_imports = defaultdict(dict)
    for total_import in total_imports_list:
        for name, md in total_import.items():
            total_imports[name].update(md)
    _, import_to_pkg = report_conda_forge_names_from_import_map(
        total_imports,
        builtin_modules=builtins,
        ignore=ignore,
    )
    return import_to_pkg
