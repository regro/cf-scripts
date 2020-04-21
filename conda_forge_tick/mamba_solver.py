"""This module has code to use mamba to test if a given package can be solved.

The basic work flow is for yaml file in .ci_support

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

from conda.models.match_spec import MatchSpec
from conda.models.channel import Channel
from conda.core.index import calculate_channel_urls, check_whitelist
from conda.core.subdir_data import cache_fn_url, create_cache_dir
import conda_build.api

from mamba import mamba_api as api

logger = logging.getLogger("conda_forge_tick.mamba_solver")


def get_index(channel_urls=(), prepend=True, platform=None,
              use_local=False, use_cache=False, unknown=None, prefix=None,
              repodata_fn="repodata.json"):
    real_urls = calculate_channel_urls(channel_urls, prepend, platform, use_local)
    check_whitelist(real_urls)

    dlist = api.DownloadTargetList()

    index = []
    for idx, url in enumerate(real_urls):
        channel = Channel(url)

        full_url = channel.url(with_credentials=True) + '/' + repodata_fn
        full_path_cache = os.path.join(
            create_cache_dir(),
            cache_fn_url(full_url, repodata_fn))

        sd = api.SubdirData(channel.name + '/' + channel.subdir,
                            full_url,
                            full_path_cache)

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
    def __init__(self, channels):
        index = get_index(channels)

        self.pool = api.Pool()
        self.repos = []

        priority = 0
        subpriority = 0  # wrong! :)
        for subdir, channel in index:
            repo = api.Repo(
                self.pool,
                str(channel),
                subdir.cache_path(),
                channel.url(with_credentials=True)
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

        # normalization can be performed using Conda's MatchSpec
        solver.add_jobs(specs, api.SOLVER_INSTALL)
        success = solver.solve()

        logger.info("MAMBA failed to solve: %s", solver.problems_to_str())

        return success


def _norm_spec(myspec):
    return MatchSpec(myspec).conda_build_form()


@functools.lru_cache(max_size=16)
def _mamba_factory(channels):
    return MambaSolver(list(channels))


def is_recipe_solvable(feedstock_dir):
    """Compute if a recipe is solvable.

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
    solvable = True

    cbcs = glob.glob(os.path.join(feedstock_dir, ".ci_support", "*.yaml"))
    for cbc_fname in cbcs:
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


def _is_recipe_solvable_on_platform(recipe_dir, cbc_path, platform, arch):
    solvable = True

    config = conda_build.config.get_or_merge_config(
                None,
                exclusive_config_file=cbc_path,
                platform=platform,
                arch=arch,
            )

    metas = conda_build.api.render(
                recipe_dir,
                platform=platform,
                arch=arch,
                ignore_system_variants=True,
                variants=config,
                permit_undefined_jinja=True,
                finalize=False,
                bypass_env_check=True,
                channel_urls=["conda-forge", "defaults"],
            )

    mamba_solver = _mamba_factory((
        "conda-forge/%s-%s" % (platform, arch),
        "conda-forge/noarch",
        "https://repo.anaconda.com/pkgs/main/%s-%s" % (platform, arch),
        "https://repo.anaconda.com/pkgs/main/noarch",
        "https://repo.anaconda.com/pkgs/r/%s-%s" % (platform, arch),
        "https://repo.anaconda.com/pkgs/r/noarch",
    ))

    for m, _, _ in metas:
        host_req = (
            m.get_value('requirements/host', [])
            or m.get_value('requirements/build', [])
        )
        host_req = [_norm_spec(s) for s in host_req]
        solvable &= mamba_solver.solve(host_req)

        run_req = m.get_value('requirements/run', [])
        run_req = [_norm_spec(s) for s in run_req]
        solvable &= mamba_solver.solve(run_req)

    return solvable
