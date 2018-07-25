import collections.abc
import logging
import subprocess
from collections import defaultdict
from concurrent.futures import as_completed, ProcessPoolExecutor

import feedparser
import networkx as nx
import requests
from conda.models.version import VersionOrder
from pkg_resources import parse_version

from .utils import parse_meta_yaml, setup_logger
import os

logger = logging.getLogger("conda_forge_tick.update_upstream_versions")


class LibrariesIO:

    def __init__(self):
        self.libraries_io_api_key = os.getenv("LIBRARIES_IO_API_KEY")
        d = defaultdict(dict)
        for proj in self.get_libraries_io_subscriptions():
            platform = proj['project']['platform'].lower()
            d[platform][proj['project']['name']] = proj
        self.data = d

    def get_libraries_io_subscriptions(self):
        if self.libraries_io_api_key == None:
            return
        l = []
        for i in range(1, 1000):
            url = "https://libraries.io/api/subscriptions?api_key={}&page={}&per_page={}&include_prerelease=False"
            url = url.format(self.libraries_io_api_key, i, 100)
            # logger.info(url.replace(self.libraries_io_api_key, "<dummy>"))
            r = retry_requests(requests.get, url)
            if r is None:
                continue
            if not r.ok or len(r.json()) == 0:
                break
            l.extend(r.json())
        return l

    def subscribe(self, platform, pkg):
        post_url = "https://libraries.io/api/subscriptions/{}/{}?api_key={}&include_prerelease=false"
        post_url = post_url.format(platform, pkg, self.libraries_io_api_key)
        r = retry_requests(requests.post, post_url)
        c = r.json()
        platform = c['project']['platform'].lower()
        self.data[platform][c['project']['name']] = c
        return c

    def get_package_versions(self, platform, pkg):
        if pkg in self.data[platform]:
            d = self.data[platform][pkg]
        else:
            d = self.subscribe(platform, pkg)
        return [ver['number'] for ver in d['project']['versions']]


libraries_io = LibrariesIO()


def urls_from_meta(meta_yaml):
    source = meta_yaml["source"]
    if isinstance(source, collections.abc.Mapping):
        source = [source]
    urls = set()
    for s in source:
        if "url" in s:
            urls.add(s["url"])
    return urls


def next_version(ver):
    ver_split = []
    ver_dot_split = ver.split(".")
    for s in ver_dot_split:
        ver_dash_split = s.split("_")
        for j in ver_dash_split:
            ver_split.append(j)
            ver_split.append("_")
        ver_split[-1] = "."
    del ver_split[-1]
    for j in reversed(range(len(ver_split))):
        try:
            t = int(ver_split[j])
        except Exception:
            continue
        else:
            ver_split[j] = str(t + 1)
            yield "".join(ver_split)
            ver_split[j] = "0"


def retry_requests(func, *args, **kwargs):
    from time import sleep
    for i in [5, 10, 20, 40]:
        r = func(*args, **kwargs)
        if r.status_code != 429:
            return r
        sleep(i)


class VersionFromFeed:
    ver_prefix_remove = ["release-", "releases%2F", "v_", "v.", "v"]
    dev_vers = ["rc", "beta", "alpha", "dev", "a", "b"]

    def get_newest_version(self, versions):
        vers = []
        for ver in versions:
            for prefix in self.ver_prefix_remove:
                if ver.startswith(prefix):
                    ver = ver[len(prefix) :]
            if any(s in ver for s in self.dev_vers):
                continue
            vers.append(ver)
        if vers:
            return max(vers, key=lambda x: VersionOrder(x.replace("-", ".")))
        else:
            return None


class Github(VersionFromFeed):
    name = "github"

    def get_package_manager_info(self, meta_yaml):
        if "github.com" not in meta_yaml["url"]:
            return
        split_url = meta_yaml["url"].lower().split("/")
        package_owner = split_url[split_url.index("github.com") + 1]
        gh_package_name = split_url[split_url.index("github.com") + 2]
        return package_owner, gh_package_name


    def get_version(self, info):
        package_owner, gh_package_name = info
        url = "https://github.com/{}/{}/releases.atom".format(
            package_owner, gh_package_name
        )
        data = feedparser.parse(url)
        if data["bozo"] == 1:
            return None
        vers = []
        for entry in data["entries"]:
            ver = entry["link"].split("/")[-1]
            vers.append(ver)
        return self.get_newest_version(vers)


class LibrariesIOFeed(VersionFromFeed):

    def get_version(self, info):
        vers = libraries_io.get_package_versions(self.name, info)
        return self.get_newest_version(vers)


class PyPI(LibrariesIOFeed):
    name = "pypi"

    def get_package_manager_info(self, meta_yaml):
        url_names = ["pypi.python.org", "pypi.org", "pypi.io"]
        source_url = meta_yaml["url"]
        if not any(s in source_url for s in url_names):
            return None
        pkg = meta_yaml["url"].split("/")[6]
        return pkg


class CRAN(LibrariesIOFeed):
    name = "cran"

    def get_package_manager_info(self, meta_yaml):
        urls = meta_yaml["url"]
        if not isinstance(meta_yaml["url"], list):
            urls = [urls]
        for url in urls:
            if "cran.r-project.org/src/contrib/Archive" not in url:
                continue
            pkg = url.split("/")[6]
            return pkg

    def get_version(self, info):
        ver = LibrariesIOFeed.get_version(self, info)
        return str(ver).replace("-", "_")


class RawURL:
    name = "RawURL"

    def get_package_manager_info(self, meta_yaml):
        if "feedstock_name" not in meta_yaml:
            return None
        if "version" not in meta_yaml:
            return None
        # TODO: pull this from the graph itself
        pkg = meta_yaml["feedstock_name"]
        content = meta_yaml["raw_meta_yaml"]

        orig_urls = urls_from_meta(meta_yaml["meta_yaml"])
        current_ver = meta_yaml["version"]
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
                        ["wget", "--spider", url], stderr=subprocess.STDOUT, timeout=1
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
                break

        if count == max_count:
            return None
        if current_ver != orig_ver:
            return current_ver

    def get_version(self, info):
        return info


def get_latest_version(meta_yaml, sources):
    for source in sources:
        info = source.get_package_manager_info(meta_yaml)
        if info is None:
            continue
        ver = source.get_version(info)
        if ver:
            return ver
        else:
            meta_yaml["bad"] = "Upstream: Could not find version on {}".format(
                source.name
            )
    if not meta_yaml.get("bad"):
        meta_yaml["bad"] = "Upstream: unknown source"
    return False


def update_upstream_versions(gx, sources=(PyPI(), CRAN(), RawURL(), Github())):
    futures = {}
    with ProcessPoolExecutor(max_workers=20) as pool:
        for node, attrs in gx.node.items():
            if attrs.get("bad") or attrs.get("archived"):
                attrs["new_version"] = False
                continue
            futures.update({pool.submit(get_latest_version, attrs, sources): (node, attrs)})
        for f in as_completed(futures):
            node, attrs = futures[f]
            try:
                attrs['new_version'] = f.result()
            except Exception as e:
                try:
                    se = str(e)
                except Exception as ee:
                    se = 'Bad exception string: {}'.format(ee)
                logger.warn(
                    "Error getting uptream version of {}: {}".format(node, se))
                attrs["bad"] = "Upstream: Error getting upstream version"
                attrs["new_version"] = False
            else:
                logger.info(
                    "{} - {} - {}".format(node, attrs["version"], attrs["new_version"])
                )

    logger.info(
        "Current number of out of date packages not PRed: {}".format(
            str(
                len(
                    [
                        n
                        for n, a in gx.node.items()
                        if a["new_version"]  # if we can get a new version
                        and a["new_version"] != a["version"]  # if we need a bump
                        and a.get("PRed", "000") != a["new_version"]  # if not PRed
                    ]
                )
            )
        )
    )


def main(args=None):
    setup_logger(logger)

    logger.info("Reading graph")
    gx = nx.read_gpickle("graph.pkl")

    update_upstream_versions(gx)

    logger.info("writing out file")
    nx.write_gpickle(gx, "graph.pkl")


if __name__ == "__main__":
    main()
