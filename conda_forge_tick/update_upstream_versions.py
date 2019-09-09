import collections.abc
import logging
import builtins
import subprocess

import feedparser
import networkx as nx
import requests
from conda.models.version import VersionOrder
from pkg_resources import parse_version

from .utils import parse_meta_yaml, setup_logger, executor, load_graph, \
    dump_graph

logger = logging.getLogger("conda_forge_tick.update_upstream_versions")


def urls_from_meta(meta_yaml):
    source = meta_yaml["source"]
    if isinstance(source, collections.abc.Mapping):
        source = [source]
    urls = set()
    for s in source:
        if "url" in s:
            # if it is a list for instance
            if not isinstance(s["url"], str):
                urls.update(s['url'])
            else:
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


class VersionFromFeed:
    ver_prefix_remove = ["release-", "releases%2F", "v_", "v.", "v"]
    dev_vers = ["rc", "beta", "alpha", "dev", "a", "b", "RC"]

    def get_version(self, url):
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
            vers.append(ver)
        if vers:
            return max(vers, key=lambda x: VersionOrder(x.replace("-", ".")))
        else:
            return None


class Github(VersionFromFeed):
    name = "github"

    def get_url(self, meta_yaml):
        if "github.com" not in meta_yaml["url"]:
            return
        split_url = meta_yaml["url"].lower().split("/")
        package_owner = split_url[split_url.index("github.com") + 1]
        gh_package_name = split_url[split_url.index("github.com") + 2]
        return "https://github.com/{}/{}/releases.atom".format(
            package_owner, gh_package_name
        )


class LibrariesIO(VersionFromFeed):
    def get_url(self, meta_yaml):
        urls = meta_yaml["url"]
        if not isinstance(meta_yaml["url"], list):
            urls = [urls]
        for url in urls:
            if self.url_contains not in url:
                continue
            pkg = self.package_name(url)
            return "https://libraries.io/{}/{}/versions.atom".format(self.name, pkg)


class PyPI:
    name = "pypi"

    def get_url(self, meta_yaml):
        url_names = ["pypi.python.org", "pypi.org", "pypi.io"]
        source_url = meta_yaml["url"]
        if not any(s in source_url for s in url_names):
            return None
        pkg = meta_yaml["url"].split("/")[6]
        return "https://pypi.org/pypi/{}/json".format(pkg)

    def get_version(self, url):
        r = requests.get(url)
        # If it is a pre-release don't give back the pre-release version
        if not r.ok or parse_version(r.json()["info"]["version"].strip()).is_prerelease:
            return False
        return r.json()["info"]["version"].strip()


class NPM:
    name = "npm"

    def get_url(self, meta_yaml):
        if "registry.npmjs.org" not in meta_yaml["url"]:
            return None
        # might be namespaced
        pkg = meta_yaml["url"].split("/")[3:-2]
        return "https://registry.npmjs.org/{}".format("/".join(pkg))

    def get_version(self, url):
        r = requests.get(url)
        if not r.ok:
            return False
        latest = r.json()["dist-tags"].get("latest", "").strip()
        # If it is a pre-release don't give back the pre-release version
        if not len(latest) or parse_version(latest).is_prerelease:
            return False

        return latest


class CRAN(LibrariesIO):
    name = "cran"
    url_contains = "cran.r-project.org/src/contrib/Archive"

    def package_name(self, url):
        return url.split("/")[6]

    def get_version(self, url):
        ver = LibrariesIO.get_version(self, url)
        return str(ver).replace("-", "_")


class RawURL:
    name = "RawURL"

    def get_url(self, meta_yaml):
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

    def get_version(self, url):
        return url


def get_latest_version(meta_yaml, sources):
    for source in sources:
        url = source.get_url(meta_yaml)
        if url is None:
            continue
        ver = source.get_version(url)
        if ver:
            return ver
        else:
            meta_yaml["bad"] = "Upstream: Could not find version on {}".format(
                source.name
            )
    if not meta_yaml.get("bad"):
        meta_yaml["bad"] = "Upstream: unknown source"
    return False


def _update_upstream_versions_sequential(gx, sources):
    to_update = []
    for node, node_attrs in gx.node.items():
        attrs = node_attrs['payload']
        if attrs.get("bad") or attrs.get("archived"):
            attrs["new_version"] = False
            continue
        to_update.append((node, attrs))
    for node, node_attrs in to_update:
        with node_attrs['payload'] as attrs:
            try:
                attrs["new_version"] = get_latest_version(attrs, sources)
            except Exception as e:
                try:
                    se = str(e)
                except Exception as ee:
                    se = "Bad exception string: {}".format(ee)
                logger.warn("Error getting uptream version of {}: {}".format(node, se))
                attrs["bad"] = "Upstream: Error getting upstream version"
                attrs["new_version"] = False
            else:
                logger.info(
                    "{} - {} - {}".format(node, attrs["version"], attrs["new_version"])
                )


def _update_upstream_versions_process_pool(gx, sources):
    futures = {}
    with executor(kind='dask', max_workers=20) as (pool, as_completed):
        for node, node_attrs in gx.node.items():
            with node_attrs['payload'] as attrs:
                if attrs.get("bad") or attrs.get("archived"):
                    attrs["new_version"] = False
                    continue
                futures.update(
                    {pool.submit(get_latest_version, attrs, sources): (node, attrs)}
                )
        for f in as_completed(futures):
            node, node_attrs = futures[f]
            with node_attrs['payload'] as attrs:
                try:
                    attrs["new_version"] = f.result()
                except Exception as e:
                    try:
                        se = str(e)
                    except Exception as ee:
                        se = "Bad exception string: {}".format(ee)
                    logger.warn("Error getting uptream version of {}: {}".format(node, se))
                    attrs["bad"] = "Upstream: Error getting upstream version"
                    attrs["new_version"] = False
                else:
                    logger.info(
                        "{} - {} - {}".format(node, attrs.get("version", "<no-version>"), attrs["new_version"])
                    )


def update_upstream_versions(gx, sources=None):
    sources = (
        (PyPI(), NPM(), CRAN(), RawURL(), Github()) if sources is None else sources
    )
    env = builtins.__xonsh__.env
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
                        for n, a in gx.node.items()
                        if a['payload'].get("new_version") and a['payload'].get('version')  # if we can get a new version
                        and a['payload']["new_version"] != a['payload']["version"]  # if we need a bump
                        and a['payload'].get("PRed", "000") != a['payload']["new_version"]  # if not PRed
                    ]
                )
            )
        )
    )


def main(args=None):
    setup_logger(logger)

    logger.info("Reading graph")
    gx = load_graph()

    update_upstream_versions(gx)

    logger.info("writing out file")
    dump_graph(gx)


if __name__ == "__main__":
    main()
