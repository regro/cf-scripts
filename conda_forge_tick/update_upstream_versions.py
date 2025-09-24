import functools
import hashlib
import logging
import os
import secrets
import time
from collections.abc import MutableMapping
from concurrent.futures import as_completed
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
    TypeVar,
    Union,
)

import networkx as nx
import tqdm
from conda_forge_feedstock_ops.container_utils import (
    get_default_log_level_args,
    run_container_operation,
    should_use_container,
)

from conda_forge_tick.cli_context import CliContext
from conda_forge_tick.executors import executor
from conda_forge_tick.lazy_json_backends import LazyJson, dumps, sync_lazy_json_object
from conda_forge_tick.settings import (
    ENV_CONDA_FORGE_ORG,
    ENV_GRAPH_GITHUB_BACKEND_REPO,
    settings,
)
from conda_forge_tick.update_sources import (
    CRAN,
    NPM,
    NVIDIA,
    AbstractSource,
    CratesIO,
    Github,
    GithubReleases,
    GitTags,
    IncrementAlphaRawURL,
    PyPI,
    RawURL,
    ROSDistro,
)
from conda_forge_tick.utils import get_keys_default, load_existing_graph
from conda_forge_tick.version_filters import is_version_ignored

T = TypeVar("T")

# conda_forge_tick :: cft
logger = logging.getLogger(__name__)

RNG = secrets.SystemRandom()


def get_latest_version_local(
    name: str,
    attrs: Mapping[str, Any],
    sources: Iterable[AbstractSource],
) -> Dict[str, Union[None, str]]:
    """Given a package, return the new version information to be written into the cf-graph.

    Parameters
    ----------
    name
        The name of the feedstock.
    attrs
        The node attributes of the feedstock.
    sources
        The version sources to use.

    Returns
    -------
    dict
        The new version information.
    """
    version_data: Dict[str, Union[None, str]] = {"new_version": None}

    if name == "ca-policy-lcg":
        logger.warning(
            "ca-policy-lcg is manually excluded from automatic version updates because it runs too long "
            "and hangs the bot",
        )
        return version_data

    version_sources = get_keys_default(
        attrs,
        ["conda-forge.yml", "bot", "version_updates", "sources"],
        {},
        None,
    )

    sources_to_use: Iterable[AbstractSource]
    if version_sources is not None:
        version_sources = [vs.lower() for vs in version_sources]
        sources_to_use_list = []
        for vs in version_sources:
            for source in sources:
                if source.name.lower() == vs:
                    sources_to_use_list.append(source)
                    break
            else:
                logger.warning(
                    "Package %s requests version source '%s' which is not available. Skipping.",
                    name,
                    vs,
                )

        sources_to_use = sources_to_use_list

        logger.debug(
            "%s defines the following custom version sources: %s",
            name,
            [source.name for source in sources_to_use],
        )
        skipped_sources = [
            source.name for source in sources if source not in sources_to_use
        ]
        if skipped_sources:
            logger.debug(
                "Therefore, we skip the following sources: %s", skipped_sources
            )
        else:
            logger.debug("No sources are skipped.")

    else:
        sources_to_use = sources

    exceptions = []
    for source in sources_to_use:
        try:
            logger.debug("Fetching latest version for %s from %s...", name, source.name)
            url = source.get_url(attrs)
            if url is None:
                continue
            logger.debug("Using URL %s", url)
            ver = source.get_version(url)
            if not ver:
                logger.debug("Upstream: Could not find version on %s", source.name)
                continue
            logger.debug("Found version %s on %s", ver, source.name)
            version_data["new_version"] = ver
            break
        except Exception as e:
            logger.error(
                "An exception occurred while fetching %s from %s.",
                name,
                source.name,
                exc_info=e,
            )
            exceptions.append(e)

    new_version = version_data["new_version"]

    if not new_version and exceptions:
        logger.error(
            "Cannot find version on any source, exceptions occurred. Raising the first exception.",
        )
        raise exceptions[0]

    if not new_version:
        logger.debug("Upstream: Could not find version on any source")
        return version_data

    if is_version_ignored(attrs, new_version):
        logger.debug(
            "Ignoring version %s because it is in the exclude list.", new_version
        )
        version_data["new_version"] = None

    return version_data


def get_latest_version_containerized(
    name: str,
    attrs: MutableMapping[str, Any],
    sources: Iterable[AbstractSource],
) -> Dict[str, Union[None, str]]:
    """Given a package, return the new version information to be written into the cf-graph.

    **This function runs the version parsing in a container.**

    Parameters
    ----------
    name
        The name of the feedstock.
    attrs
        The node attributes of the feedstock.
    sources
        The version sources to use.

    Returns
    -------
    dict
        The new version information.
    """
    if "feedstock_name" not in attrs:
        attrs["feedstock_name"] = name

    args = [
        "conda-forge-tick-container",
        "get-latest-version",
        "--existing-feedstock-node-attrs",
        "-",
        "--sources",
        ",".join([source.name for source in sources]),
    ]
    args += get_default_log_level_args(logger)

    json_blob = dumps(attrs.data) if isinstance(attrs, LazyJson) else dumps(attrs)

    return run_container_operation(
        args,
        input=json_blob,
        extra_container_args=[
            "-e",
            f"{ENV_CONDA_FORGE_ORG}={settings().conda_forge_org}",
            "-e",
            f"{ENV_GRAPH_GITHUB_BACKEND_REPO}={settings().graph_github_backend_repo}",
        ],
    )


def get_latest_version(
    name: str,
    attrs: MutableMapping[str, Any],
    sources: Iterable[AbstractSource],
    use_container: bool | None = None,
) -> Dict[str, Union[None, str]]:
    """Given a package, return the new version information to be written into the cf-graph.

    Parameters
    ----------
    name
        The name of the feedstock.
    attrs
        The node attributes of the feedstock.
    sources
        The version sources to use.
    use_container : bool, optional
        Whether to use a container to run the version parsing.
        If None, the function will use a container if the environment
        variable `CF_FEEDSTOCK_OPS_IN_CONTAINER` is 'false'. This feature can be
        used to avoid container in container calls.

    Returns
    -------
    dict
        The new version information.
    """
    if should_use_container(use_container=use_container):
        return get_latest_version_containerized(name, attrs, sources)
    else:
        return get_latest_version_local(name, attrs, sources)


def get_job_number_for_package(name: str, n_jobs: int):
    """Get the job number for a package.

    Parameters
    ----------
    name
        The name of the package.
    n_jobs
        The total number of jobs.

    Returns
    -------
    int
        The job number for the package.
    """
    return abs(int(hashlib.sha1(name.encode("utf-8")).hexdigest(), 16)) % n_jobs + 1


def filter_nodes_for_job(
    all_nodes: Iterable[Tuple[str, T]],
    job: int,
    n_jobs: int,
) -> Iterator[Tuple[str, T]]:
    """Filter nodes for a specific job.

    Parameters
    ----------
    all_nodes
        All nodes to filter.
    job
        The job number.
    n_jobs
        The total number of jobs.

    Returns
    -------
    Iterator[Tuple[str, T]]
        The filtered nodes.
    """
    return (t for t in all_nodes if get_job_number_for_package(t[0], n_jobs) == job)


def include_node(package_name: str, payload_attrs: Mapping) -> bool:
    """Given a package name and its node attributes, determine whether
    the package should be included in the update process.

    Also log the reason why a package is not included.

    Parameters
    ----------
    package_name
        The name of the package.
    payload_attrs
        The cf-graph node payload attributes for the package.

    Returns
    -------
    bool
        True if the package should be included, False otherwise.
    """
    pr_info = payload_attrs.get("pr_info", {})

    if payload_attrs.get("parsing_error"):
        logger.debug(
            "Skipping %s because it is marked as having a parsing error. The error is printed below.\n%s",
            package_name,
            payload_attrs["parsing_error"],
        )
        return False

    if payload_attrs.get("archived"):
        logger.debug("Skipping %s because it is marked as archived.", package_name)
        return False

    if pr_info.get("bad") and "Upstream" not in pr_info.get("bad"):
        logger.debug(
            "Skipping %s because its corresponding Pull Request is "
            "marked as bad with a non-upstream issue. The error is printed below.\n%s",
            package_name,
            pr_info["bad"],
        )
        return False

    if pr_info.get("bad"):
        logger.debug(
            "Note: %s has a bad Pull Request, but this is marked as an upstream issue. "
            "Therefore, it will be included in the update process. The error is printed below.\n%s",
            package_name,
            pr_info["bad"],
        )
        # no return here

    return True


def _update_upstream_versions_sequential(
    to_update: Iterable[Tuple[str, MutableMapping]],
    sources: Iterable[AbstractSource],
) -> None:
    node_count = 0
    for node, attrs in to_update:
        # checking each node
        version_data: Dict[str, Union[None, str]] = {}

        # New version request
        try:
            # check for latest version
            version_data.update(get_latest_version(node, attrs, sources))
        except Exception as e:
            try:
                se = repr(e)
            except Exception as ee:
                se = f"Bad exception string: {ee}"
            logger.warning(
                "Warning: Error getting upstream version of %s: %s", node, se
            )
            version_data["bad"] = "Upstream: Error getting upstream version"
        else:
            logger.info(
                "# %-5s - %s - %s -> %s",
                node_count,
                node,
                attrs.get("version"),
                version_data.get("new_version"),
            )

        logger.debug("writing out file")
        lazyjson = LazyJson(f"versions/{node}.json")
        with lazyjson as version_attrs:
            version_attrs.clear()
            version_attrs.update(version_data)
        node_count += 1


def _update_upstream_versions_process_pool(
    to_update: Iterable[Tuple[str, Mapping]],
    sources: Iterable[AbstractSource],
) -> None:
    futures = {}
    # we use threads here since all of the work is done in a container anyways
    with executor(kind="thread", max_workers=5) as pool:
        for node, attrs in tqdm.tqdm(
            to_update,
            ncols=80,
            desc="submitting version update jobs",
        ):
            if RNG.random() > settings().frac_update_upstream_versions:
                continue

            futures.update(
                {
                    pool.submit(get_latest_version, node, attrs, sources): (
                        node,
                        attrs,
                    ),
                },
            )

        n_tot = len(futures)
        n_left = len(futures)
        start = time.time()
        # eta :: elapsed time average
        eta = -1.0
        for f in as_completed(futures):
            n_left -= 1
            if n_left % 10 == 0:
                eta = (time.time() - start) / (n_tot - n_left) * n_left

            node, attrs = futures[f]
            version_data = {}
            try:
                # check for latest version
                version_data.update(f.result())
            except Exception as e:
                try:
                    se = repr(e)
                except Exception as ee:
                    se = f"Bad exception string: {ee}"
                logger.error(
                    "itr % 5d - eta % 5ds: Error getting upstream version of %s: %s",
                    n_left,
                    eta,
                    node,
                    se,
                )
                version_data["bad"] = "Upstream: Error getting upstream version"
            else:
                logger.info(
                    "itr % 5d - eta % 5ds: %s - %s -> %s",
                    n_left,
                    eta,
                    node,
                    attrs.get("version", "<no-version>"),
                    version_data["new_version"],
                )
            # writing out file
            lazyjson = LazyJson(f"versions/{node}.json")
            with lazyjson as version_attrs:
                changed = version_attrs.data != version_data
                version_attrs.clear()
                version_attrs.update(version_data)

            if changed:
                try:
                    sync_lazy_json_object(version_attrs, "file", ["github_api"])
                except Exception:
                    # will sync in deploy later if this fails
                    pass


@functools.lru_cache(maxsize=1)
def all_version_sources():
    return (
        PyPI(),
        CRAN(),
        CratesIO(),
        NPM(),
        Github(),
        GithubReleases(),
        NVIDIA(),
        ROSDistro(),
        GitTags(),
        RawURL(),
        IncrementAlphaRawURL(),
    )


def update_upstream_versions(
    gx: nx.DiGraph,
    sources: Optional[Iterable[AbstractSource]] = None,
    debug: bool = False,
    job=1,
    n_jobs=1,
    package: Optional[str] = None,
) -> None:
    """Update the upstream versions of packages.

    Parameters
    ----------
    gx
        The conda forge graph.
    sources
        The sources to use for fetching the upstream versions.
    debug
        Whether to run in debug mode.
    job
        The job number.
    n_jobs
        The total number of jobs.
    package
        The package to update. If None, update all packages.
    """
    if package and package not in gx.nodes:
        logger.error("Package %s not found in graph. Exiting.", package)
        return

    # In the future, we should have some sort of typed graph structure
    all_nodes: Iterable[Tuple[str, Mapping[str, Mapping]]] = (
        [(package, gx.nodes.get(package))] if package else gx.nodes.items()
    )

    job_nodes = filter_nodes_for_job(all_nodes, job, n_jobs)

    if not job_nodes:
        logger.info("No packages to update for job %d", job)
        return

    def extract_payload(node: Tuple[str, Mapping[str, Mapping]]) -> Tuple[str, Mapping]:
        name, attrs = node
        return name, attrs["payload"]

    payload_extracted = map(extract_payload, job_nodes)

    to_update: List[Tuple[str, Mapping]] = list(
        filter(
            lambda node: include_node(node[0], node[1]),
            payload_extracted,
        ),
    )

    RNG.shuffle(to_update)

    sources = all_version_sources() if sources is None else sources

    updater = (
        _update_upstream_versions_sequential
        if debug or package
        else _update_upstream_versions_process_pool
    )

    logger.info("Updating upstream versions")
    updater(to_update, sources)


def main(
    ctx: CliContext,
    job: int = 1,
    n_jobs: int = 1,
    package: Optional[str] = None,
) -> None:
    """Update the upstream version of packages.

    This is the main entry point for the update function.

    Parameters
    ----------
    ctx
        The CLI context.
    job
        The job number.
    n_jobs
        The total number of jobs.
    package
        The package to update. If None, update all packages.
    """
    logger.info("Reading graph")
    # Graph enabled for inspection
    gx = load_existing_graph()

    # Check if 'versions' folder exists or create a new one;
    os.makedirs("versions", exist_ok=True)
    # call update
    update_upstream_versions(
        gx,
        debug=ctx.debug,
        job=job,
        n_jobs=n_jobs,
        package=package,
    )
