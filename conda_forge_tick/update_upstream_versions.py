import abc

import collections.abc
import logging
import builtins
import subprocess
import hashlib
import re
from concurrent.futures import as_completed
from typing import Any, Optional, Iterable, Callable

import yaml
import networkx as nx

import feedparser
import requests
from conda.models.version import VersionOrder

# TODO: parse_version has bad type annotations
from pkg_resources import parse_version

from .utils import parse_meta_yaml, setup_logger, executor, load_graph, dump_graph

import typing
from typing import Set, Iterator

if typing.TYPE_CHECKING:
    from .migrators_types import MetaYamlTypedDict, SourceTypedDict

logger = logging.getLogger("conda_forge_tick.update_upstream_versions")

CRAN_INDEX: Optional[dict] = None


def urls_from_meta(meta_yaml: "MetaYamlTypedDict") -> Set[str]:
    source: "SourceTypedDict" = meta_yaml["source"]
    sources: typing.List["SourceTypedDict"]
    if isinstance(source, collections.abc.Mapping):
        sources = [source]
    else:
        sources = typing.cast("typing.List[SourceTypedDict]", source)
    urls = set()
    for s in sources:
        if "url" in s:
            # if it is a list for instance
            if not isinstance(s["url"], str):
                urls.update(s["url"])
            else:
                urls.add(s["url"])
    return urls


def next_version(ver: str) -> Iterator[str]:
    ver_split = []
    ver_dot_split = ver.split(".")
    for s in ver_dot_split:
        ver_dash_split = s.split("_")
        for j in ver_dash_split:
            ver_split.append(j)
            ver_split.append("_")
        ver_split[-1] = "."
    del ver_split[-1]
    for k in reversed(range(len(ver_split))):
        try:
            t = int(ver_split[k])
        except Exception:
            continue
        else:
            ver_split[k] = str(t + 1)
            yield "".join(ver_split)
            ver_split[k] = "0"


class AbstractSource(abc.ABC):
    name: str

    @abc.abstractmethod
    def get_version(self, url: str) -> Optional[str]:
        pass

    @abc.abstractmethod
    def get_url(self, url: str) -> Optional[str]:
        pass


class VersionFromFeed(AbstractSource):
    ver_prefix_remove = ["release-", "releases%2F", "v_", "v.", "v"]
    dev_vers = ["rc", "beta", "alpha", "dev", "a", "b", "RC"]

    def get_version(self, url) -> Optional[str]:
        data = feedparser.parse(url)
        if data["bozo"] == 1:
            return None
        vers = []
        for entry in data["entries"]:
            ver = entry["link"].split("/")[-1]
            for prefix in self.ver_prefix_remove:
                if ver.startswith(prefix):
                    ver = ver[len(prefix) :]
            if any(s in ver for s in self.dev_vers):
                continue
            # Extract vesion number starting at the first digit.
            ver = re.search(r"(\d+[^\s]*)", ver).group(0)
            vers.append(ver)
        if vers:
            return max(vers, key=lambda x: VersionOrder(x.replace("-", ".")))
        else:
            return None


class Github(VersionFromFeed):
    name = "github"

    def get_url(self, meta_yaml) -> Optional[str]:
        if "github.com" not in meta_yaml["url"]:
            return None
        split_url = meta_yaml["url"].lower().split("/")
        package_owner = split_url[split_url.index("github.com") + 1]
        gh_package_name = split_url[split_url.index("github.com") + 2]
        return "https://github.com/{}/{}/releases.atom".format(
            package_owner, gh_package_name,
        )


class LibrariesIO(VersionFromFeed):
    def get_url(self, meta_yaml) -> Optional[str]:
        urls = meta_yaml["url"]
        if not isinstance(meta_yaml["url"], list):
            urls = [urls]
        for url in urls:
            if self.url_contains not in url:
                continue
            pkg = self.package_name(url)
            return f"https://libraries.io/{self.name}/{pkg}/versions.atom"


class PyPI(AbstractSource):
    name = "pypi"

    def get_url(self, meta_yaml) -> Optional[str]:
        url_names = ["pypi.python.org", "pypi.org", "pypi.io"]
        source_url = meta_yaml["url"]
        if not any(s in source_url for s in url_names):
            return None
        pkg = meta_yaml["url"].split("/")[6]
        return f"https://pypi.org/pypi/{pkg}/json"

    def get_version(self, url) -> Optional[str]:
        r = requests.get(url)
        # If it is a pre-release don't give back the pre-release version
        if not r.ok or parse_version(r.json()["info"]["version"].strip()).is_prerelease:
            return False
        return r.json()["info"]["version"].strip()


class NPM(AbstractSource):
    name = "npm"

    def get_url(self, meta_yaml) -> Optional[str]:
        if "registry.npmjs.org" not in meta_yaml["url"]:
            return None
        # might be namespaced
        pkg = meta_yaml["url"].split("/")[3:-2]
        return "https://registry.npmjs.org/{}".format("/".join(pkg))

    def get_version(self, url: str) -> Optional[str]:
        r = requests.get(url)
        if not r.ok:
            return False
        latest = r.json()["dist-tags"].get("latest", "").strip()
        # If it is a pre-release don't give back the pre-release version
        if not len(latest) or parse_version(latest).is_prerelease:
            return False

        return latest


class CRAN(AbstractSource):
    """The CRAN versions source.

    Uses a local CRAN index instead of one request per package.

    The index is lazy initialzed on first `get_url` call and kept in
    memory on module level as `CRAN_INDEX` like a singelton. This way it
    is shared on executor level and not serialized with every instance of
    the CRAN class to allow efficient distributed execution with e.g.
    dask.
    """

    name = "cran"
    url_contains = "cran.r-project.org/src/contrib/Archive"
    cran_url = "https://cran.r-project.org"

    def init(self) -> None:
        global CRAN_INDEX
        if not CRAN_INDEX:
            try:
                session = requests.Session()
                CRAN_INDEX = self._get_cran_index(session)
                logger.info("Cran source initialized")
            except Exception:
                logger.error("Cran initialization failed", exc_info=True)
                CRAN_INDEX = {}

    def _get_cran_index(self, session: requests.Session) -> dict:
        # from conda_build/skeletons/cran.py:get_cran_index
        logger.info("Fetching cran index from %s", self.cran_url)
        r = session.get(self.cran_url + "/src/contrib/")
        r.raise_for_status()
        records = {}
        for p in re.findall(r'<td><a href="([^"]+)">\1</a></td>', r.text):
            if p.endswith(".tar.gz") and "_" in p:
                name, version = p.rsplit(".", 2)[0].split("_", 1)
                records[name.lower()] = (name, version)
        r = session.get(self.cran_url + "/src/contrib/Archive/")
        r.raise_for_status()
        for p in re.findall(r'<td><a href="([^"]+)/">\1/</a></td>', r.text):
            if re.match(r"^[A-Za-z]", p):
                records.setdefault(p.lower(), (p, None))
        return records

    def get_url(self, meta_yaml) -> Optional[str]:
        self.init()
        urls = meta_yaml["url"]
        if not isinstance(meta_yaml["url"], list):
            urls = [urls]
        for url in urls:
            if self.url_contains not in url:
                continue
            # alternatively: pkg = meta_yaml["name"].split("r-", 1)[-1]
            pkg = url.split("/")[6].lower()
            if pkg in CRAN_INDEX:
                return CRAN_INDEX[pkg]
            else:
                return None
        return None

    def get_version(self, url) -> Optional[str]:
        return str(url[1]).replace("-", "_") if url[1] else None


ROS_DISTRO_INDEX: Optional[dict] = None


class ROSDistro(AbstractSource):
    name = "rosdistro"

    def parse_idx(self, distro_name: str = "melodic") -> dict:
        session = requests.Session()
        res = session.get(
            "https://raw.githubusercontent.com/ros/rosdistro/master/{distro}/distribution.yaml".format(
                distro=distro_name,
            ),
        )
        res.raise_for_status()
        resd = yaml.load(res.text, Loader=yaml.SafeLoader)
        repos = resd["repositories"]

        result_dict: dict = {distro_name: {"reverse": {}, "forward": {}}}
        for k, v in repos.items():
            if not v.get("release"):
                continue
            if v["release"].get("packages"):
                for p in v["release"]["packages"]:
                    result_dict[distro_name]["reverse"][self.encode_ros_name(p)] = (
                        k,
                        p,
                    )
            else:
                result_dict[distro_name]["reverse"][self.encode_ros_name(k)] = (k, k)
        result_dict[distro_name]["forward"] = repos
        return result_dict

    def encode_ros_name(self, name: str) -> str:
        new_name = name.replace("_", "-")
        if new_name.startswith("ros-"):
            return new_name
        else:
            return "ros-" + new_name

    def init(self) -> None:
        global ROS_DISTRO_INDEX
        if not ROS_DISTRO_INDEX:
            self.version_url_cache = {}
            try:
                ROS_DISTRO_INDEX = self.parse_idx("melodic")
                logger.info("ROS Distro source initialized")
            except Exception:
                logger.error("ROS Distro initialization failed", exc_info=True)
                ROS_DISTRO_INDEX = {}

    def get_url(self, meta_yaml: "MetaYamlTypedDict") -> Optional[str]:
        if not meta_yaml["name"].startswith("ros-"):
            return None

        self.init()

        toplevel_package, package = ROS_DISTRO_INDEX["melodic"]["reverse"][
            meta_yaml["name"]
        ]

        p_dict = ROS_DISTRO_INDEX["melodic"]["forward"][toplevel_package]
        version = p_dict["release"]["version"]
        tag_url = p_dict["release"]["tags"]["release"].format(
            package=package, version=version,
        )
        url = p_dict["release"]["url"]

        if url.endswith(".git"):
            url = url[:-4]

        final_url = f"{url}/archive/{tag_url}.tar.gz"
        self.version_url_cache[final_url] = version.split("-")[0]

        return final_url

    def get_version(self, url):
        return self.version_url_cache[url]


def get_sha256(url: str) -> Optional[str]:
    try:
        from rever import hash_url

        return hash_url(url, "sha256")
    except ImportError:
        pass
    try:
        filename = hashlib.sha256(url.encode("utf-8")).hexdigest()
        output = subprocess.check_output(
            ["wget", url, "-O", filename], stderr=subprocess.STDOUT,
        )
        output = subprocess.check_output(["sha256sum", filename])
        return output.decode("utf-8").split(" ")[0]
    except Exception:
        return None


class RawURL(AbstractSource):
    name = "RawURL"

    def get_url(self, meta_yaml) -> Optional[str]:
        if "feedstock_name" not in meta_yaml:
            return None
        if "version" not in meta_yaml:
            return None
        # TODO: pull this from the graph itself
        pkg = meta_yaml["feedstock_name"]
        content = meta_yaml["raw_meta_yaml"]

        orig_urls = urls_from_meta(meta_yaml["meta_yaml"])
        current_ver = meta_yaml["version"]
        current_sha256 = None
        orig_ver = current_ver
        found = True
        count = 0
        max_count = 10
        while found and count < max_count:
            found = False
            for next_ver in next_version(current_ver):
                new_content = content.replace(orig_ver, next_ver)
                meta = parse_meta_yaml(new_content)
                url = None
                for u in urls_from_meta(meta):
                    if u not in orig_urls:
                        url = u
                        break
                if url is None:
                    meta_yaml["bad"] = "Upstream: no url in yaml"
                    return None
                if (
                    str(meta["package"]["version"]) != next_ver
                    or meta_yaml["url"] == url
                ):
                    continue
                try:
                    output = subprocess.check_output(
                        ["wget", "--spider", url], stderr=subprocess.STDOUT, timeout=1,
                    )
                except Exception:
                    continue
                # For FTP servers an exception is not thrown
                if "No such file" in output.decode("utf-8"):
                    continue
                if "not retrieving" in output.decode("utf-8"):
                    continue
                found = True
                count = count + 1
                current_ver = next_ver
                new_sha256 = get_sha256(url)
                if new_sha256 == current_sha256 or new_sha256 in new_content:
                    return None
                current_sha256 = new_sha256
                break

        if count == max_count:
            return None
        if current_ver != orig_ver:
            return current_ver
        return None

    def get_version(self, url: str) -> str:
        return url


def get_latest_version(payload_meta_yaml: Any, sources: Iterable[AbstractSource]):
    with payload_meta_yaml as meta_yaml:
        for source in sources:
            url = source.get_url(meta_yaml)
            if url is None:
                continue
            ver = source.get_version(url)
            if ver:
                return ver
            else:
                meta_yaml["bad"] = "Upstream: Could not find version on {}".format(
                    source.name,
                )
        if not meta_yaml.get("bad"):
            meta_yaml["bad"] = "Upstream: unknown source"
        return False


def _update_upstream_versions_sequential(
    gx: nx.DiGraph, sources: Iterable[AbstractSource],
) -> None:
    to_update = []
    for node, node_attrs in gx.nodes.items():
        attrs = node_attrs["payload"]
        if attrs.get("bad") or attrs.get("archived"):
            attrs["new_version"] = False
            continue
        to_update.append((node, attrs))
    for node, node_attrs in to_update:
        with node_attrs as attrs:
            try:
                new_version = get_latest_version(attrs, sources)
                attrs["new_version"] = new_version or attrs["new_version"]
            except Exception as e:
                try:
                    se = str(e)
                except Exception as ee:
                    se = f"Bad exception string: {ee}"
                logger.warning(f"Error getting uptream version of {node}: {se}")
                attrs["bad"] = "Upstream: Error getting upstream version"
            else:
                logger.info(
                    "{} - {} - {}".format(
                        node, attrs.get("version"), attrs.get("new_version"),
                    ),
                )


def _update_upstream_versions_process_pool(
    gx: nx.DiGraph, sources: Iterable[AbstractSource],
) -> None:
    futures = {}
    with executor(kind="dask", max_workers=20) as pool:
        for node, node_attrs in gx.nodes.items():
            with node_attrs["payload"] as attrs:
                if attrs.get("bad") or attrs.get("archived"):
                    attrs["new_version"] = False
                    continue
                futures.update(
                    {pool.submit(get_latest_version, attrs, sources): (node, attrs)},
                )
        for f in as_completed(futures):
            node, node_attrs = futures[f]
            with node_attrs as attrs:
                try:
                    new_version = f.result()
                    attrs["new_version"] = new_version or attrs["new_version"]
                except Exception as e:
                    try:
                        se = str(e)
                    except Exception as ee:
                        se = f"Bad exception string: {ee}"
                    logger.warn(f"Error getting uptream version of {node}: {se}")
                    attrs["bad"] = "Upstream: Error getting upstream version"
                else:
                    logger.info(
                        "{} - {} - {}".format(
                            node,
                            attrs.get("version", "<no-version>"),
                            attrs["new_version"],
                        ),
                    )


def update_upstream_versions(
    gx: nx.DiGraph, sources: Iterable[AbstractSource] = None,
) -> None:
    sources = (
        (PyPI(), NPM(), CRAN(), ROSDistro(), RawURL(), Github())
        if sources is None
        else sources
    )
    from .xonsh_utils import env

    debug = env.get("CONDA_FORGE_TICK_DEBUG", False)
    updater = (
        _update_upstream_versions_sequential
        if debug
        else _update_upstream_versions_process_pool
    )
    logger.info("Updating upstream versions")
    updater(gx, sources)
    logger.info(
        "Current number of out of date packages not PRed: {}".format(
            str(
                len(
                    [
                        n
                        for n, a in gx.nodes.items()
                        if a["payload"].get("new_version")
                        and a["payload"].get("version")  # if we can get a new version
                        and a["payload"]["new_version"]
                        != a["payload"]["version"]  # if we need a bump
                        and a["payload"].get("PRed", "000")
                        != a["payload"]["new_version"]  # if not PRed
                    ],
                ),
            ),
        ),
    )


def main(args: Any = None) -> None:
    setup_logger(logger)

    logger.info("Reading graph")
    gx = load_graph()

    update_upstream_versions(gx)

    logger.info("writing out file")
    dump_graph(gx)


if __name__ == "__main__":
    main()
