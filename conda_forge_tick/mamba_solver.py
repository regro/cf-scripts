"""This module has code to use mamba to test if a given package can be solved.

The basic workflow is for yaml file in .ci_support

1. run the conda_build api to render the recipe
2. pull out the host/build and run requirements, possibly for more than one output.
3. send them to mamba to check if they can be solved.

Most of the code here is due to @wolfv in this gist,
https://gist.github.com/wolfv/cd12bd4a448c77ff02368e97ffdf495a.
"""
import rapidjson as json
import os
import logging
import glob
import functools
import requests
import pathlib
import pprint
import tempfile
import copy
import subprocess
import atexit
import time
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Tuple, List, FrozenSet, Set, Iterable

import psutil
from ruamel.yaml import YAML
import stopit

from conda.models.match_spec import MatchSpec
from conda.models.channel import Channel
from conda.core.index import calculate_channel_urls, check_whitelist
from conda.core.subdir_data import cache_fn_url, create_cache_dir
import conda_build.api
import conda_package_handling.api

from mamba import mamba_api as api

from conda_build.conda_interface import pkgs_dirs
from conda_build.utils import download_channeldata

PACKAGE_CACHE = api.MultiPackageCache(pkgs_dirs)

logger = logging.getLogger("conda_forge_tick.mamba_solver")

DEFAULT_RUN_EXPORTS = {
    "weak": set(),
    "strong": set(),
    "noarch": set(),
}
LIBCFGRAPH_INDEX = None


# turn off pip for python
api.Context().add_pip_as_python_dependency = False

# these characters are start requirements that do not need to be munged from
# 1.1 to 1.1.*
REQ_START = ["!=", "==", ">", "<", ">=", "<="]


def _munge_req_star(req):
    reqs = []

    # now we split on ',' and '|'
    # once we have all of the parts, we then munge the star
    csplit = req.split(",")
    ncs = len(csplit)
    for ic, p in enumerate(csplit):

        psplit = p.split("|")
        nps = len(psplit)
        for ip, pp in enumerate(psplit):
            # clear white space
            pp = pp.strip()

            # finally add the star if we need it
            if any(pp.startswith(__v) for __v in REQ_START) or "*" in pp:
                reqs.append(pp)
            else:
                if pp.startswith("="):
                    pp = pp[1:]
                reqs.append(pp + ".*")

            # add | back on the way out
            if ip != nps - 1:
                reqs.append("|")

        # add , back on the way out
        if ic != ncs - 1:
            reqs.append(",")

    # put it all together
    return "".join(reqs)


def _norm_spec(myspec):
    m = MatchSpec(myspec)

    # this code looks like MatchSpec.conda_build_form() but munges stars in the
    # middle
    parts = [m.get_exact_value("name")]

    version = m.get_raw_value("version")
    build = m.get_raw_value("build")
    if build and not version:
        raise RuntimeError("spec '%s' has build but not version!" % myspec)

    if version:
        parts.append(_munge_req_star(m.version.spec_str))
    if build:
        parts.append(build)

    return " ".join(parts)


def get_index(
    channel_urls=(),
    prepend=True,
    platform=None,
    use_local=False,
    use_cache=False,
    unknown=None,
    prefix=None,
    repodata_fn="repodata.json",
):
    """Get an index?

    Function from @wolfv here:
    https://gist.github.com/wolfv/cd12bd4a448c77ff02368e97ffdf495a.
    """
    real_urls = calculate_channel_urls(channel_urls, prepend, platform, use_local)
    check_whitelist(real_urls)

    dlist = api.DownloadTargetList()

    index = []
    for idx, url in enumerate(real_urls):
        channel = Channel(url)

        full_url = channel.url(with_credentials=True) + "/" + repodata_fn
        full_path_cache = os.path.join(
            create_cache_dir(),
            cache_fn_url(full_url, repodata_fn),
        )

        sd = api.SubdirData(
            channel.name + "/" + channel.subdir,
            full_url,
            full_path_cache,
        )

        sd.load()
        index.append((sd, channel))
        dlist.add(sd)

    is_downloaded = dlist.download(True)

    if not is_downloaded:
        raise RuntimeError("Error downloading repodata.")

    return index


@dataclass(frozen=True)
class FakePackage:
    name: str
    version: str = "1.0"
    build_string: str = ""
    build_number: int = 0
    noarch: str = ""
    depends: FrozenSet[str] = field(default_factory=frozenset)
    timestamp: int = field(
        default_factory=lambda: int(time.mktime(time.gmtime()) * 1000),
    )

    def to_repodata_entry(self):
        out = self.__dict__.copy()
        if self.build_string:
            build = f"{self.build_string}_{self.build_number}"
        else:
            build = f"{self.build_number}"
        out["depends"] = list(out["depends"])
        out["build"] = build
        fname = f"{self.name}-{self.version}-{build}.tar.bz2"
        return fname, out


class FakeRepoData:
    def __init__(self, base_dir: pathlib.Path):
        self.base_path = base_dir
        self.packages_by_subdir: Dict[FakePackage, Set[str]] = defaultdict(set)

    @property
    def channel_url(self):
        return f"file://{str(self.base_path.absolute())}"

    def add_package(self, package: FakePackage, subdirs: Iterable[str] = ()):
        subdirs = frozenset(subdirs)
        if not subdirs:
            subdirs = frozenset(["noarch"])
        self.packages_by_subdir[package].update(subdirs)

    def _write_subdir(self, subdir):
        packages = {}
        out = {"info": {"subdir": subdir}, "packages": packages}
        for pkg, subdirs in self.packages_by_subdir.items():
            if subdir not in subdirs:
                continue
            fname, info_dict = pkg.to_repodata_entry()
            info_dict["subdir"] = subdir
            packages[fname] = info_dict

        (self.base_path / subdir).mkdir(exist_ok=True)
        (self.base_path / subdir / "repodata.json").write_text(json.dumps(out))

    def write(self):
        all_subdirs = {
            "noarch",
            "linux-aarch64",
            "linux-ppc64le",
            "linux-64",
            "osx-64",
            "osx-arm64",
            "win-64",
        }
        for subdirs in self.packages_by_subdir.values():
            all_subdirs.update(subdirs)

        for subdir in all_subdirs:
            self._write_subdir(subdir)

        logger.info("Wrote fake repodata to %s", self.base_path)
        import glob

        for filename in glob.iglob(str(self.base_path / "**"), recursive=True):
            logger.info(filename)
        logger.info("repo: %s", self.channel_url)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.write()


def _get_run_export_download(link_tuple):
    c, pkg, jdata = link_tuple

    with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP")) as tmpdir:
        try:
            # download
            subprocess.run(
                f"cd {tmpdir} && curl -s -L {c}/{pkg} --output {pkg}",
                shell=True,
            )

            # unpack and read if it exists
            if os.path.exists(f"{tmpdir}/{pkg}"):
                conda_package_handling.api.extract(f"{tmpdir}/{pkg}")

            if pkg.endswith(".tar.bz2"):
                pkg_nm = pkg[: -len(".tar.bz2")]
            else:
                pkg_nm = pkg[: -len(".conda")]

            rxpth = f"{tmpdir}/{pkg_nm}/info/run_exports.json"

            if os.path.exists(rxpth):
                with open(rxpth) as fp:
                    run_exports = json.load(fp)
            else:
                run_exports = {}

            for key in DEFAULT_RUN_EXPORTS:
                if key in run_exports:
                    logger.debug(
                        "RUN EXPORT: %s %s %s",
                        pkg,
                        key,
                        run_exports.get(key, []),
                    )
                run_exports[key] = set(run_exports.get(key, []))

        except Exception as e:
            print("Could not get run exports for %s: %s", pkg, repr(e))
            run_exports = None
            pass

    return link_tuple, run_exports


@functools.lru_cache(maxsize=10240)
def _get_run_export(link_tuple):

    global LIBCFGRAPH_INDEX

    run_exports = None

    cd = download_channeldata(link_tuple[0].rsplit("/", maxsplit=1)[0])
    data = json.loads(link_tuple[2])
    name = data["name"]

    if cd.get("packages", {}).get(name, {}).get("run_exports", {}):
        # libcfgraph location
        if link_tuple[1].endswith(".tar.bz2"):
            pkg_nm = link_tuple[1][: -len(".tar.bz2")]
        else:
            pkg_nm = link_tuple[1][: -len(".conda")]
        channel_subdir = "/".join(link_tuple[0].split("/")[-2:])
        libcfg_pth = f"artifacts/{name}/" f"{channel_subdir}/{pkg_nm}.json"
        if LIBCFGRAPH_INDEX is None:
            logger.warning("downloading libcfgraph file index")
            r = requests.get(
                "https://raw.githubusercontent.com/regro/libcfgraph"
                "/master/.file_listing.json",
            )
            LIBCFGRAPH_INDEX = r.json()

        if libcfg_pth in LIBCFGRAPH_INDEX:
            data = requests.get(
                os.path.join(
                    "https://raw.githubusercontent.com",
                    "regro/libcfgraph/master",
                    libcfg_pth,
                ),
            ).json()

            rx = data.get("rendered_recipe", {}).get("build", {}).get("run_exports", {})
            if rx:
                run_exports = copy.deepcopy(
                    DEFAULT_RUN_EXPORTS,
                )
                if isinstance(rx, str):
                    # some packages have a single string
                    # eg pyqt
                    rx = [rx]

                for k in rx:
                    if k in DEFAULT_RUN_EXPORTS:
                        logger.debug(
                            "RUN EXPORT: %s %s %s",
                            name,
                            k,
                            rx[k],
                        )
                        run_exports[k].update(rx[k])
                    else:
                        logger.debug(
                            "RUN EXPORT: %s %s %s",
                            name,
                            "weak",
                            [k],
                        )
                        run_exports["weak"].add(k)

        # fall back to getting repodata shard if needed
        if run_exports is None:
            logger.info(
                "RUN EXPORTS: downloading package %s/%s"
                % (link_tuple[0], link_tuple[1]),
            )
            run_exports = _get_run_export_download(link_tuple)[1]
    else:
        run_exports = copy.deepcopy(DEFAULT_RUN_EXPORTS)

    return run_exports


def prerun_solver(channels, platform, specs):
    data = dict(
        channels=channels,
        platform=platform,
        specs=specs,
    )
    data_str = json.dumps(data)
    proc = subprocess.Popen(
        'mamba-is-solvable \'%s\'' % data_str,
        shell=True,
    )

    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    if proc.returncode is None or proc.returncode != 0:
        success = False
    else:
        success = True

    return success


class MambaSolver:
    """Run the mamba solver.

    Parameters
    ----------
    channels : list of str
        A list of the channels (e.g., `[conda-forge/linux-64]`, etc.)
    platform : str
        The platform to be used (e.g., `linux-64`).

    Example
    -------
    >>> solver = MambaSolver(['conda-forge/linux-64', 'conda-forge/noarch'], "linux-64")
    >>> solver.solve(["xtensor 0.18"])
    """

    def __init__(self, channels, platform):
        self.channels = channels
        self.platform = platform
        index = get_index(channels, platform=platform)

        self.pool = api.Pool()
        self.repos = []

        priority = 0
        subpriority = 0  # wrong! :)
        for subdir, channel in index:
            repo = api.Repo(
                self.pool,
                str(channel),
                subdir.cache_path(),
                channel.url(with_credentials=True),
            )
            repo.set_priority(priority, subpriority)
            self.repos.append(repo)

    def solve(self, specs, get_run_exports=False, precheck=True):
        """Solve given a set of specs.

        Parameters
        ----------
        specs : list of str
            A list of package specs. You can use `conda.models.match_spec.MatchSpec`
            to get them to the right form by calling
            `MatchSpec(mypec).conda_build_form()`
        get_run_exports : bool, optional
            If True, return run exports else do not.
        precheck : bool, optional
            If True, run a pre-solving check to make sure mamba does not hang.

        Returns
        -------
        solvable : bool
            True if the set of specs has a solution, False otherwise.
        err : str
            The errors as a string. If no errors, is None.
        solution : list of str
            A list of concrete package specs for the env.
        run_exports : dict of list of str
            A dictionary with the weak and strong run exports for the packages.
            Only returned if get_run_exports is True.
        """
        solver_options = [(api.SOLVER_FLAG_ALLOW_DOWNGRADE, 1)]
        solver = api.Solver(self.pool, solver_options)

        _specs = [_norm_spec(s) for s in specs]

        logger.info("MAMBA running solver for specs \n\n%s", pprint.pformat(_specs))

        # sometimes the solver hangs so we precheck it in another process
        if precheck and not prerun_solver(self.channels, self.platform, _specs):
            return (
                False,
                None,
                copy.deepcopy(DEFAULT_RUN_EXPORTS),
            )

        solver.add_jobs(_specs, api.SOLVER_INSTALL)
        success = solver.solve()

        err = None
        if not success:
            logger.warning(
                "MAMBA failed to solve specs \n\n%s\n\nfor channels "
                "\n\n%s\n\nThe reported errors are:\n\n%s",
                pprint.pformat(_specs),
                pprint.pformat(self.channels),
                solver.problems_to_str(),
            )
            err = solver.problems_to_str()
            solution = None
            run_exports = copy.deepcopy(DEFAULT_RUN_EXPORTS)
        else:
            t = api.Transaction(solver, PACKAGE_CACHE)
            solution = []
            _, to_link, _ = t.to_conda()
            for _, _, jdata in to_link:
                data = json.loads(jdata)
                solution.append(
                    " ".join([data["name"], data["version"], data["build"]]),
                )

            if get_run_exports:
                logger.info(
                    "MAMBA getting run exports for \n\n%s",
                    pprint.pformat(solution),
                )
                run_exports = self._get_run_exports(to_link)

        if get_run_exports:
            return success, err, solution, run_exports
        else:
            return success, err, solution

    def _get_run_exports(self, link_tuples):
        """Given tuples of (channel, file, json repodata shard) produce a
        dict with the weak and strong run exports for the packages.
        """
        run_exports = copy.deepcopy(DEFAULT_RUN_EXPORTS)
        for link_tuple in link_tuples:
            rx = _get_run_export(link_tuple)
            for key in DEFAULT_RUN_EXPORTS:
                run_exports[key] |= rx[key]

        return run_exports


@functools.lru_cache(maxsize=32)
def _mamba_factory(channels, platform):
    return MambaSolver(list(channels), platform)


@functools.lru_cache(maxsize=1)
def virtual_package_repodata():
    # TODO: we might not want to use TemporaryDirectory
    import tempfile
    import shutil

    # tmp directory in github actions
    runner_tmp = os.environ.get("RUNNER_TEMP")
    tmp_dir = tempfile.mkdtemp(dir=runner_tmp)

    if not runner_tmp:
        # no need to bother cleaning up on CI
        def clean():
            shutil.rmtree(tmp_dir, ignore_errors=True)

        atexit.register(clean)

    tmp_path = pathlib.Path(tmp_dir)
    repodata = FakeRepoData(tmp_path)
    fake_packages = [
        FakePackage("__glibc", "2.12"),
        FakePackage("__glibc", "2.17"),
        FakePackage("__cuda", "9.2"),
        FakePackage("__cuda", "10.0"),
        FakePackage("__cuda", "10.1"),
        FakePackage("__cuda", "10.2"),
        FakePackage("__cuda", "11.0"),
        FakePackage("__cuda", "11.1"),
    ]
    for pkg in fake_packages:
        repodata.add_package(pkg)
    for osx_ver in [
        "10.9",
        "10.10",
        "10.11",
        "10.12",
        "10.13",
        "10.14",
        "10.15",
        "10.16",
    ]:
        repodata.add_package(FakePackage("__osx", osx_ver), subdirs=["osx-64"])
    for osx_ver in ["11.0"]:
        repodata.add_package(
            FakePackage("__osx", osx_ver),
            subdirs=["osx-64", "osx-arm64"],
        )
    repodata.write()

    return repodata.channel_url


def is_recipe_solvable(
    feedstock_dir,
    additional_channels=(),
) -> Tuple[bool, List[str], Dict[str, bool]]:
    """Compute if a recipe is solvable.

    We look through each of the conda build configs in the feedstock
    .ci_support dir and test each ones host and run requirements.
    The final result is a logical AND of all of the results for each CI
    support config.

    Parameters
    ----------
    feedstock_dir : str
        The directory of the feedstock.

    Returns
    -------
    solvable : bool
        The logical AND of the solvability of the recipe on all platforms
        in the CI scripts.
    errors : list of str
        A list of errors from mamba. Empty if recipe is solvable.
    solvable_by_variant : dict
        A lookup by variant config that shows if a particular config is solvable
    """

    if not additional_channels:
        additional_channels = [virtual_package_repodata()]
    os.environ["CONDA_OVERRIDE_GLIBC"] = "2.50"

    errors = []
    cbcs = sorted(glob.glob(os.path.join(feedstock_dir, ".ci_support", "*.yaml")))
    if len(cbcs) == 0:
        errors.append(
            "No `.ci_support/*.yaml` files found! This can happen when a rerender "
            "results in no builds for a recipe (e.g., a recipe is python 2.7 only). "
            "This attempted migration is being reported as not solvable.",
        )
        logger.warning(errors[-1])
        return False, errors, {}

    if not os.path.exists(os.path.join(feedstock_dir, "recipe", "meta.yaml")):
        errors.append(
            "No `recipe/meta.yaml` file found! This issue is quite weird and "
            "someone should investigate!",
        )
        logger.warning(errors[-1])
        return False, errors, {}

    solvable = True
    solvable_by_cbc = {}
    for cbc_fname in cbcs:
        # we need to extract the platform (e.g., osx, linux) and arch (e.g., 64, aarm64)
        # conda smithy forms a string that is
        #
        #  {{ platform }} if arch == 64
        #  {{ platform }}_{{ arch }} if arch != 64
        #
        # Thus we undo that munging here.
        _parts = os.path.basename(cbc_fname).split("_")
        platform = _parts[0]
        arch = _parts[1]
        if arch not in ["32", "aarch64", "ppc64le", "armv7l"]:
            arch = "64"

        _solvable, _errors = _is_recipe_solvable_on_platform(
            os.path.join(feedstock_dir, "recipe"),
            cbc_fname,
            platform,
            arch,
            additional_channels=additional_channels,
        )
        solvable = solvable and _solvable
        cbc_name = os.path.basename(cbc_fname).rsplit(".", maxsplit=1)[0]
        errors.extend([f"{cbc_name}: {e}" for e in _errors])
        solvable_by_cbc[cbc_name] = _solvable

    del os.environ["CONDA_OVERRIDE_GLIBC"]

    return solvable, errors, solvable_by_cbc


def _clean_reqs(reqs, names):
    reqs = [r for r in reqs if not any(r.split(" ")[0] == nm for nm in names)]
    return reqs


def _filter_problematic_reqs(reqs):
    """There are some reqs that have issues when used in certain contexts"""
    problem_reqs = {
        # This causes a strange self-ref for arrow-cpp
        "parquet-cpp",
    }
    reqs = [r for r in reqs if r.split(" ")[0] not in problem_reqs]
    return reqs


def apply_pins(reqs, host_req, build_req, outnames, m):
    from conda_build.render import get_pin_from_build

    pin_deps = host_req if m.is_cross else build_req

    full_build_dep_versions = {
        dep.split()[0]: " ".join(dep.split()[1:])
        for dep in _clean_reqs(pin_deps, outnames)
    }

    pinned_req = []
    for dep in reqs:
        try:
            pinned_req.append(
                get_pin_from_build(m, dep, full_build_dep_versions),
            )
        except Exception:
            # in case we couldn't apply pins for whatever
            # reason, fall back to the req
            pinned_req.append(dep)

    pinned_req = _filter_problematic_reqs(pinned_req)
    return pinned_req


def _is_recipe_solvable_on_platform(
    recipe_dir,
    cbc_path,
    platform,
    arch,
    additional_channels=(),
):
    # parse the channel sources from the CBC
    parser = YAML(typ="jinja2")
    parser.indent(mapping=2, sequence=4, offset=2)
    parser.width = 320

    with open(cbc_path) as fp:
        cbc_cfg = parser.load(fp.read())

    if "channel_sources" in cbc_cfg:
        channel_sources = cbc_cfg["channel_sources"][0].split(",")
    else:
        channel_sources = ["conda-forge", "defaults", "msys2"]

    if "msys2" not in channel_sources:
        channel_sources.append("msys2")

    if additional_channels:
        channel_sources = list(additional_channels) + channel_sources

    logger.debug(
        "MAMBA: using channels %s on platform-arch %s-%s",
        channel_sources,
        platform,
        arch,
    )

    # here we extract the conda build config in roughly the same way that
    # it would be used in a real build
    logger.info("rendering recipe with conda build")

    config = conda_build.config.get_or_merge_config(
        None,
        platform=platform,
        arch=arch,
        variant_config_files=[cbc_path],
    )
    cbc, _ = conda_build.variants.get_package_combined_spec(recipe_dir, config=config)

    # now we render the meta.yaml into an actual recipe
    metas = conda_build.api.render(
        recipe_dir,
        platform=platform,
        arch=arch,
        ignore_system_variants=True,
        variants=cbc,
        permit_undefined_jinja=True,
        finalize=False,
        bypass_env_check=True,
        channel_urls=channel_sources,
    )

    # now we loop through each one and check if we can solve it
    # we check run and host and ignore the rest
    logger.info("getting mamba solver")
    solver = _mamba_factory(tuple(channel_sources), f"{platform}-{arch}")
    solvable = True
    errors = []
    outnames = [m.name() for m, _, _ in metas]
    for m, _, _ in metas:
        logger.info("checking recipe %s", m.name())

        build_req = m.get_value("requirements/build", [])
        host_req = m.get_value("requirements/host", [])
        run_req = m.get_value("requirements/run", [])

        if build_req:
            build_req = _clean_reqs(build_req, outnames)
            _solvable, _err, build_req, build_rx = solver.solve(
                build_req,
                get_run_exports=True,
            )
            solvable = solvable and _solvable
            if _err is not None:
                errors.append(_err)

            if m.is_cross:
                host_req = list(set(host_req) | build_rx["strong"])
                if not (m.noarch or m.noarch_python):
                    run_req = list(set(run_req) | build_rx["strong"])
            else:
                if m.noarch or m.noarch_python:
                    if m.build_is_host:
                        run_req = list(set(run_req) | build_rx["noarch"])
                else:
                    run_req = list(set(run_req) | build_rx["strong"])
                    if m.build_is_host:
                        run_req = list(set(run_req) | build_rx["weak"])
                    else:
                        host_req = list(set(host_req) | build_rx["strong"])

        if host_req:
            host_req = _clean_reqs(host_req, outnames)
            _solvable, _err, host_req, host_rx = solver.solve(
                host_req,
                get_run_exports=True,
            )
            solvable = solvable and _solvable
            if _err is not None:
                errors.append(_err)

            if m.is_cross:
                if m.noarch or m.noarch_python:
                    run_req = list(set(run_req) | host_rx["noarch"])
                else:
                    run_req = list(set(run_req) | host_rx["weak"])

        if run_req:
            run_req = apply_pins(run_req, host_req or [], build_req or [], outnames, m)
            run_req = _clean_reqs(run_req, outnames)
            _solvable, _err, _ = solver.solve(run_req)
            solvable = solvable and _solvable
            if _err is not None:
                errors.append(_err)

        tst_req = (
            m.get_value("test/requires", [])
            + m.get_value("test/requirements", [])
            + run_req
        )
        if tst_req:
            tst_req = _clean_reqs(tst_req, outnames)
            _solvable, _err, _ = solver.solve(tst_req)
            solvable = solvable and _solvable
            if _err is not None:
                errors.append(_err)

    logger.info("RUN EXPORT cache status: %s", _get_run_export.cache_info())
    logger.info(
        "MAMBA SOLVER MEM USAGE: %dMB",
        psutil.Process().memory_info().rss // 1024 ** 2,
    )

    return solvable, errors
