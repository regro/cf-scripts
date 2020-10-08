"""This module has code to use mamba to test if a given package can be solved.

The basic workflow is for yaml file in .ci_support

1. run the conda_build api to render the recipe
2. pull out the host/build and run requirements, possibly for more than one output.
3. send them to mamba to check if they can be solved.

Most of the code here is due to @wolfv in this gist,
https://gist.github.com/wolfv/cd12bd4a448c77ff02368e97ffdf495a.
"""
import os
import logging
import glob
import functools
import pprint

from ruamel.yaml import YAML

from conda.models.match_spec import MatchSpec
from conda.models.channel import Channel
from conda.core.index import calculate_channel_urls, check_whitelist
from conda.core.subdir_data import cache_fn_url, create_cache_dir
import conda_build.api

from mamba import mamba_api as api

logger = logging.getLogger("conda_forge_tick.mamba_solver")


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


class MambaSolver:
    """Run the mamba solver.

    Parameters
    ----------
    channels : list of str
        A list of the channels (e.g., `[conda-forge/linux-64]`, etc.)

    Example
    -------
    >>> solver = MambaSolver(['conda-forge/linux-64', 'conda-forge/noarch'])
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

    def solve(self, specs):
        """Solve given a set of specs.

        Parameters
        ----------
        specs : list of str
            A list of package specs. You can use `conda.models.match_spec.MatchSpec`
            to get them to the right form by calling
            `MatchSpec(mypec).conda_build_form()`

        Returns
        -------
        solvable : bool
            True if the set of specs has a solution, False otherwise.
        """
        solver_options = [(api.SOLVER_FLAG_ALLOW_DOWNGRADE, 1)]
        solver = api.Solver(self.pool, solver_options)

        _specs = [_norm_spec(s) for s in specs]

        solver.add_jobs(_specs, api.SOLVER_INSTALL)
        success = solver.solve()

        if not success:
            logger.warning(
                "MAMBA failed to solve specs \n\n%s\n\nfor channels "
                "\n\n%s\n\nThe reported errors are:\n\n%s",
                pprint.pformat(_specs),
                pprint.pformat(self.channels),
                solver.problems_to_str(),
            )

        return success


@functools.lru_cache(maxsize=32)
def _mamba_factory(channels, platform):
    return MambaSolver(list(channels), platform)


def is_recipe_solvable(feedstock_dir):
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
    """

    cbcs = sorted(glob.glob(os.path.join(feedstock_dir, ".ci_support", "*.yaml")))
    if len(cbcs) == 0:
        logger.warning(
            "No `.ci_support/*.yaml` files found! This can happen when a rerender "
            "results in no builds for a recipe (e.g., a recipe is python 2.7 only). "
            "This attempted migration is being reported as not solvable.",
        )
        return False

    if not os.path.exists(os.path.join(feedstock_dir, "recipe", "meta.yaml")):
        logger.warning(
            "No `recipe/meta.yaml` file found! This issue is quite weird and "
            "someone should investigate!",
        )
        return False

    solvable = True
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

        solvable &= _is_recipe_solvable_on_platform(
            os.path.join(feedstock_dir, "recipe"),
            cbc_fname,
            platform,
            arch,
        )

    return solvable


def _clean_reqs(reqs, names):
    return [r for r in reqs if not any(r.split(" ")[0] == nm for nm in names)]


def _is_recipe_solvable_on_platform(recipe_dir, cbc_path, platform, arch):
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

    logger.debug(
        "MAMBA: using channels %s on platform-arch %s-%s",
        channel_sources,
        platform,
        arch,
    )

    # here we extract the conda build config in roughly the same way that
    # it would be used in a real build
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
    mamba_solver = _mamba_factory(tuple(channel_sources), f"{platform}-{arch}")

    solvable = True
    outnames = [m.name() for m, _, _ in metas]
    for m, _, _ in metas:
        build_req = m.get_value("requirements/build", [])
        if build_req:
            build_req = _clean_reqs(build_req, outnames)
            solvable &= mamba_solver.solve(build_req)

        host_req = m.get_value("requirements/host", [])
        if host_req:
            host_req = _clean_reqs(host_req, outnames)
            solvable &= mamba_solver.solve(host_req)

        run_req = m.get_value("requirements/run", [])
        run_req = _clean_reqs(run_req, outnames)
        solvable &= mamba_solver.solve(run_req)

        tst_req = (
            m.get_value("test/requires", [])
            + m.get_value("test/requirements", [])
            + run_req
        )
        tst_req = _clean_reqs(tst_req, outnames)
        solvable &= mamba_solver.solve(tst_req)

    return solvable
