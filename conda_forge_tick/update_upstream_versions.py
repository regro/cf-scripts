import subprocess
import collections.abc
import networkx as nx
import requests
from pkg_resources import parse_version

from conda.models.version import VersionOrder
import feedparser

from .utils import parse_meta_yaml

import logging

logger = logging.getLogger("conda_forge_tick.update_upstream_versions")


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
    ver_prefix_remove = ["release-", "releases%2F", "v"]
    dev_vers = ["rc", "beta", "alpha", "dev", "a", "b"]

    def get_version(self, url):
        data = feedparser.parse(url)
        if data["bozo"] == 1:
            return None
        vers = []
        for entry in data["entries"]:
            ver = entry["link"].split("/")[-1]
            for prefix in self.ver_prefix_remove:
                if ver.startswith(prefix):
                    ver = ver[len(prefix):]
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
        url_template = "https://raw.githubusercontent.com/conda-forge/" \
                       "{}-feedstock/master/recipe/meta.yaml"
        try:
            resp = requests.get(url_template.format(pkg))
            resp.raise_for_status()
            content = resp.content
            content = content.decode("utf-8")
        except Exception:
            return None

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
                source = meta["source"]
                if isinstance(source, collections.abc.Mapping):
                    source = [source]
                url = None
                for s in source:
                    if next_ver in s.get("url", ""):
                        url = s["url"]
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


def update_upstream_versions(gx, sources=(PyPI(), CRAN(), RawURL(), Github())):
    for node, attrs in gx.node.items():
        if attrs.get("bad") or attrs.get("archived"):
            attrs["new_version"] = False
            continue
        try:
            attrs["new_version"] = get_latest_version(attrs, sources)
        except Exception as e:
            logger.warn("Error getting uptream version of {}: {}".format(node, e))
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
    logging.basicConfig(level=logging.ERROR)
    logger.setLevel(logging.INFO)

    logger.info("Reading graph")
    gx = nx.read_gpickle("graph.pkl")

    update_upstream_versions(gx)

    logger.info("writing out file")
    nx.write_gpickle(gx, "graph.pkl")


if __name__ == "__main__":
    main()
