import functools
import hashlib
import logging
import os
import secrets
import time
from concurrent.futures import as_completed
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Literal,
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
from conda_forge_tick.lazy_json_backends import LazyJson, dumps
from conda_forge_tick.settings import (
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
    IncrementAlphaRawURL,
    PyPI,
    RawURL,
    ROSDistro,
)
from conda_forge_tick.utils import get_keys_default, load_existing_graph

T = TypeVar("T")

# conda_forge_tick :: cft
logger = logging.getLogger(__name__)

RNG = secrets.SystemRandom()


def ignore_version(attrs: Mapping[str, Any], version: str) -> bool:
    """
    Check if a version should be ignored based on the `conda-forge.yml` file.
    :param attrs: The node attributes
    :param version: The version to check
    :return: True if the version should be ignored, False otherwise
    """
    versions_to_ignore = get_keys_default(
        attrs,
        ["conda-forge.yml", "bot", "version_updates", "exclude"],
        {},
        [],
    )
    return (
        version.replace("-", ".") in versions_to_ignore or version in versions_to_ignore
    )


def get_latest_version_local(
    name: str,
    attrs: Mapping[str, Any],
    sources: Iterable[AbstractSource],
) -> Dict[str, Union[Literal[False], str]]:
    """
    Given a package, return the new version information to be written into the cf-graph.

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
    version_data : dict
        The new version information.
    """
    version_data: Dict[str, Union[Literal[False], str]] = {"new_version": False}

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
                    f"Package {name} requests version source '{vs}' which is not available. Skipping.",
                )

        sources_to_use = sources_to_use_list

        logger.debug(
            f"{name} defines the following custom version sources: {[source.name for source in sources_to_use]}",
        )
        skipped_sources = [
            source.name for source in sources if source not in sources_to_use
        ]
        if skipped_sources:
            logger.debug(f"Therefore, we skip the following sources: {skipped_sources}")
        else:
            logger.debug("No sources are skipped.")

    else:
        sources_to_use = sources

    exceptions = []
    for source in sources_to_use:
        try:
            logger.debug(f"Fetching latest version for {name} from {source.name}...")
            url = source.get_url(attrs)
            if url is None:
                continue
            logger.debug(f"Using URL {url}")
            ver = source.get_version(url)
            if not ver:
                logger.debug(f"Upstream: Could not find version on {source.name}")
                continue
            logger.debug(f"Found version {ver} on {source.name}")
            version_data["new_version"] = ver
            break
        except Exception as e:
            logger.error(
                f"An exception occurred while fetching {name} from {source.name}: {e}",
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

    if ignore_version(attrs, new_version):
        logger.debug(
            f"Ignoring version {new_version} because it is in the exclude list.",
        )
        version_data["new_version"] = False

    return version_data


def get_latest_version_containerized(
    name: str,
    attrs: Mapping[str, Any],
    sources: Iterable[AbstractSource],
) -> Dict[str, Union[Literal[False], str]]:
    """
    Given a package, return the new version information to be written into the cf-graph.

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
    version_data : dict
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
    )


def get_latest_version(
    name: str,
    attrs: Mapping[str, Any],
    sources: Iterable[AbstractSource],
    use_container: bool | None = None,
) -> Dict[str, Union[Literal[False], str]]:
    """
    Given a package, return the new version information to be written into the cf-graph.

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
    version_data : dict
        The new version information.
    """
    if should_use_container(use_container=use_container):
        return get_latest_version_containerized(name, attrs, sources)
    else:
        return get_latest_version_local(name, attrs, sources)


def get_job_number_for_package(name: str, n_jobs: int):
    return abs(int(hashlib.sha1(name.encode("utf-8")).hexdigest(), 16)) % n_jobs + 1


def filter_nodes_for_job(
    all_nodes: Iterable[Tuple[str, T]],
    job: int,
    n_jobs: int,
) -> Iterator[Tuple[str, T]]:
    return (t for t in all_nodes if get_job_number_for_package(t[0], n_jobs) == job)


def include_node(package_name: str, payload_attrs: Mapping) -> bool:
    """
    Given a package name and its node attributes, determine whether
    the package should be included in the update process.

    Also log the reason why a package is not included.

    :param package_name: The name of the package
    :param payload_attrs: The cf-graph node payload attributes for the package
    :return: True if the package should be included, False otherwise
    """
    pr_info = payload_attrs.get("pr_info", {})

    if payload_attrs.get("parsing_error"):
        logger.debug(
            f"Skipping {package_name} because it is marked as having a parsing error. The error is printed below.\n"
            f"{payload_attrs['parsing_error']}",
        )
        return False

    if payload_attrs.get("archived"):
        logger.debug(
            f"Skipping {package_name} because it is marked as archived.",
        )
        return False

    if pr_info.get("bad") and "Upstream" not in pr_info.get("bad"):
        logger.debug(
            f"Skipping {package_name} because its corresponding Pull Request is "
            f"marked as bad with a non-upstream issue. The error is printed below.\n"
            f"{pr_info['bad']}",
        )
        return False

    if pr_info.get("bad"):
        logger.debug(
            f"Note: {package_name} has a bad Pull Request, but this is marked as an upstream issue. "
            f"Therefore, it will be included in the update process. The error is printed below.\n"
            f"{pr_info['bad']}",
        )
        # no return here

    return True


def _update_upstream_versions_sequential(
    to_update: Iterable[Tuple[str, Mapping]],
    sources: Iterable[AbstractSource],
) -> None:
    node_count = 0
    for node, attrs in to_update:
        # checking each node
        version_data: Dict[str, Union[Literal[False], str]] = {}

        # New version request
        try:
            # check for latest version
            version_data.update(get_latest_version(node, attrs, sources))
        except Exception as e:
            try:
                se = repr(e)
            except Exception as ee:
                se = f"Bad exception string: {ee}"
            logger.warning(f"Warning: Error getting upstream version of {node}: {se}")
            version_data["bad"] = "Upstream: Error getting upstream version"
        else:
            logger.info(
                f"# {node_count:<5} - {node} - {attrs.get('version')} "
                f"-> {version_data.get('new_version')}",
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
            if RNG.random() >= settings().frac_update_upstream_versions:
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
                    "itr % 5d - eta % 5ds: "
                    "Error getting upstream version of %s: %s"
                    % (n_left, eta, node, se),
                )
                version_data["bad"] = "Upstream: Error getting upstream version"
            else:
                logger.info(
                    "itr % 5d - eta % 5ds: %s - %s -> %s"
                    % (
                        n_left,
                        eta,
                        node,
                        attrs.get("version", "<no-version>"),
                        version_data["new_version"],
                    ),
                )
            # writing out file
            lazyjson = LazyJson(f"versions/{node}.json")
            with lazyjson as version_attrs:
                version_attrs.clear()
                version_attrs.update(version_data)


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
    """
    Update the upstream versions of packages.
    :param gx: The conda forge graph
    :param sources: The sources to use for fetching the upstream versions
    :param debug: Whether to run in debug mode
    :param job: The job number
    :param n_jobs: The total number of jobs
    :param package: The package to update. If None, update all packages.
    """
    if package and package not in gx.nodes:
        logger.error(f"Package {package} not found in graph. Exiting.")
        return

    # In the future, we should have some sort of typed graph structure
    all_nodes: Iterable[Tuple[str, Mapping[str, Mapping]]] = (
        [(package, gx.nodes.get(package))] if package else gx.nodes.items()
    )

    job_nodes = filter_nodes_for_job(all_nodes, job, n_jobs)

    if not job_nodes:
        logger.info(f"No packages to update for job {job}")
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
    """
    Main function for updating the upstream versions of packages.
    :param ctx: The CLI context.
    :param job: The job number.
    :param n_jobs: The total number of jobs.
    :param package: The package to update. If None, update all packages.
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
