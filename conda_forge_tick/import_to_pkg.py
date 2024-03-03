import bz2
import hashlib
import io
import json
import logging
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import chain, groupby
from typing import List

import requests
from conda_forge_metadata.artifact_info import get_artifact_info_as_json
from tqdm import tqdm

from conda_forge_tick.cli_context import CliContext
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    dump,
    lazy_json_override_backends,
    load,
)

logger = logging.getLogger(__name__)


CLOBBER_EXCEPTIONS = {
    "matplotlib",
    "matplotlib-base",
    "mongo",
}

NUM_LETTERS = 10

IMPORT_TO_PKG_DIR = "import_to_pkg_maps"
IMPORT_TO_PKG_DIR_INDEX = os.path.join(
    IMPORT_TO_PKG_DIR, f"{IMPORT_TO_PKG_DIR}_indexed_files"
)
IMPORT_TO_PKG_DIR_CLOBBERING = os.path.join(
    IMPORT_TO_PKG_DIR,
    f"{IMPORT_TO_PKG_DIR}_clobbering_pkgs.json",
)
IMPORT_TO_PKG_DIR_META = os.path.join(
    IMPORT_TO_PKG_DIR, f"{IMPORT_TO_PKG_DIR}_meta.json"
)
IMPORT_TO_PKG_DIR_SHARD = 20

CONDA_SUBDIRS = [
    "freebsd-64",
    "linux-32",
    "linux-64",
    "linux-aarch64",
    "linux-armv6l",
    "linux-armv7l",
    "linux-ppc64",
    "linux-ppc64le",
    "linux-riscv64",
    "linux-s390x",
    "noarch",
    "osx-64",
    "osx-arm64",
    "win-32",
    "win-64",
    "win-arm64",
    "zos-z",
]


def fetch_arch(arch):
    # Generate a set a urls to generate for an channel/arch combo
    try:
        logger.info(f"fetching {arch}")
        r = requests.get(
            f"https://conda.anaconda.org/conda-forge/{arch}/repodata.json.bz2"
        )
        r.raise_for_status()
        repodata = json.load(bz2.BZ2File(io.BytesIO(r.content)))
    except Exception as e:
        logger.error(f"Failed to fetch {arch}: {e}")
        return

    logger.info(
        "    found %d .conda artifacts" % (len(repodata["packages.conda"])),
    )
    logger.info(
        "    found %d .tar.bz2 artifacts" % (len(repodata["packages"])),
    )
    for p in repodata["packages.conda"]:
        yield f"{arch}/{p}"

    for p in repodata["packages"]:
        yield f"{arch}/{p}"


def _get_all_artifacts():
    logger.info("Fetching all artifacts from conda-forge.")
    all_artifacts = set()
    for subdir in CONDA_SUBDIRS:
        for artifact in fetch_arch(subdir):
            all_artifacts.add(artifact)
    return all_artifacts


def _get_head_letters(name):
    return name[: min(NUM_LETTERS, len(name))].lower()


def _fname_to_index(fname):
    return (
        abs(int(hashlib.sha1(fname.encode("utf-8")).hexdigest(), 16))
        % IMPORT_TO_PKG_DIR_SHARD
    )


def _file_path_to_import(file_path: str):
    file_path = file_path.split("site-packages/")[-1].split(".egg/")[-1]
    if ".so" in file_path:
        if "python" not in file_path and "pypy" not in file_path:
            return
        file_path = file_path.split(".", 1)[0]
    elif ".pyd" in file_path:
        file_path = file_path.split(".", 1)[0]
    return (
        file_path.replace("/__init__.py", "")
        .replace("/__main__.py", "")
        .replace(".py", "")
        .replace(".pyd", "")
        .replace("/", ".")
    )


def _extract_importable_files(file_list):
    output_list = []
    for file in file_list:
        if "site-packages/" in file:
            if file.rsplit("/", 1)[0] + "/__init__.py" in file_list:
                output_list.append(file)
            elif file.endswith(".so") or file.endswith(".pyd"):
                output_list.append(file)
            elif (
                len(file.split("site-packages/")[-1].split(".egg/")[-1].split("/")) == 1
            ):
                output_list.append(file)
    return output_list


def _get_imports_and_files(file):
    from contextlib import redirect_stderr, redirect_stdout
    from io import StringIO

    outerr = StringIO()
    try:
        with redirect_stdout(outerr), redirect_stderr(outerr):
            data = get_artifact_info_as_json(
                "conda-forge",
                os.path.dirname(file),
                os.path.basename(file),
                backend="oci",
            )
    except Exception as e:
        logger.error(f"Failed to get artifact info for {file}: {e}")
        data = None

    if data is None:
        return set(), []

    pkg_files: List[str] = _extract_importable_files(data.get("files", []))
    # TODO: handle top level things that are stand alone .py files
    return (
        {
            _file_path_to_import(pkg_file)
            for pkg_file in pkg_files
            if any(pkg_file.endswith(k) for k in [".py", ".pyd", ".so"])
        }
        - {None},
        data.get("files", []),
    )


def _write_out_maps(gn, import_map):
    with LazyJson(f"{IMPORT_TO_PKG_DIR}/{gn}.json") as old_map:
        for k in list(import_map):
            if k not in old_map:
                old_map[k] = set()
            old_map[k].update(import_map[k])


def main_import_to_pkg(max_artifacts: int):
    import_map = defaultdict(set)

    indexed_files = set()
    for i in range(IMPORT_TO_PKG_DIR_SHARD):
        if os.path.exists(f"{IMPORT_TO_PKG_DIR_INDEX}_{i}"):
            with open(f"{IMPORT_TO_PKG_DIR_INDEX}_{i}") as f:
                indexed_files.update({ff.strip() for ff in f.readlines()})

    clobbers = set()

    futures = {}
    all_files = _get_all_artifacts()
    if len(all_files) == 0:
        logger.error("No artifacts found.")
        return
    new_files = all_files - indexed_files
    logger.info(
        f"Found {len(new_files)} new files to index "
        f"out of {len(all_files)} total "
        f"({(1 - len(new_files)/len(all_files))*100:0.4}% indexed).",
    )

    with ProcessPoolExecutor(max_workers=4) as exc:
        n_sub = 0
        for file in tqdm(
            new_files,
            total=min(max_artifacts, len(new_files)),
            desc="submitting artifact scan jobs",
            ncols=80,
        ):
            artifact_name = os.path.basename(file)
            if artifact_name.endswith(".tar.bz2"):
                artifact_name = artifact_name[:-8]
            elif artifact_name.endswith(".conda"):
                artifact_name = artifact_name[:-6]

            futures[exc.submit(_get_imports_and_files, file)] = (artifact_name, file)
            n_sub += 1

            if n_sub == max_artifacts:
                break

        del new_files

        files_indexed = set()
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="getting artifact scan results",
            ncols=80,
        ):
            f, fext = futures.pop(future)
            files_indexed.add(fext)
            imports, files = future.result()
            pkg = f.rsplit("-", 2)[0]
            for impt in imports:
                import_map[impt].add(pkg)
                if (
                    not impt.startswith(pkg.replace("-", "_"))
                    and pkg not in CLOBBER_EXCEPTIONS
                ):
                    clobbers.add(pkg)

        os.makedirs(IMPORT_TO_PKG_DIR, exist_ok=True)
        sorted_imports = sorted(import_map.keys(), key=lambda x: x.lower())
        for gn, keys in tqdm(
            groupby(sorted_imports, lambda x: _get_head_letters(x)),
            desc="writing import maps",
            ncols=80,
        ):
            sub_import_map = {k: import_map.pop(k) for k in keys}
            exc.submit(_write_out_maps, gn, sub_import_map)

    fnames_by_index = {}
    for fname in chain(indexed_files, files_indexed):
        index = _fname_to_index(fname)
        fnames_by_index.setdefault(index, set()).add(fname)

    for index, fnames in fnames_by_index.items():
        with open(f"{IMPORT_TO_PKG_DIR_INDEX}_{index}", "w") as fp:
            fp.write("\n".join(sorted(fnames)))

    try:
        with open(IMPORT_TO_PKG_DIR_CLOBBERING) as f:
            _clobbers = load(f)
    except FileNotFoundError:
        _clobbers = set()
    _clobbers.update(clobbers)

    with open(IMPORT_TO_PKG_DIR_CLOBBERING, "w") as f:
        dump(_clobbers, f)

    with open(IMPORT_TO_PKG_DIR_META, "w") as f:
        dump({"num_letters": NUM_LETTERS, "n_files": IMPORT_TO_PKG_DIR_SHARD}, f)


def main(ctx: CliContext, max_artifacts: int = 10000) -> None:
    if not ctx.debug:
        with lazy_json_override_backends(["file"]):
            main_import_to_pkg(max_artifacts)
    else:
        main_import_to_pkg(max_artifacts)
