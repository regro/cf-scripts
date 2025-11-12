import abc
import collections.abc
import copy
import functools
import json
import logging
import re
import subprocess
import typing
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterator, List, Optional

import feedparser
import orjson
import requests
import yaml
from conda.models.version import VersionOrder
from packaging.version import InvalidVersion, Version
from packaging.version import parse as parse_version

from conda_forge_tick.migrators_types import (
    AttrsTypedDict,
    RecipeTypedDict,
    SourceTypedDict,
)
from conda_forge_tick.utils import (
    get_keys_default,
    get_platform_arch_from_ci_support_filename,
    parse_meta_yaml,
    parse_recipe_yaml,
)
from conda_forge_tick.version_filters import is_tag_ignored, is_version_ignored

from .hashing import hash_url

CRAN_INDEX: Optional[dict] = None

logger = logging.getLogger(__name__)


def urls_from_meta(meta_yaml: RecipeTypedDict) -> set[str]:
    if "source" not in meta_yaml:
        return set()

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


def _split_alpha_num(ver: str) -> List[str]:
    for i, c in enumerate(ver):
        if c.isalpha():
            return [ver[0:i], ver[i:]]
    return [ver]


def next_version(ver: str, increment_alpha: bool = False) -> Iterator[str]:
    ver_split = []
    ver_dot_split = ver.split(".")
    n_dot = len(ver_dot_split)
    for idot, sdot in enumerate(ver_dot_split):
        ver_under_split = sdot.split("_")
        n_under = len(ver_under_split)
        for iunder, sunder in enumerate(ver_under_split):
            ver_dash_split = sunder.split("-")
            n_dash = len(ver_dash_split)
            for idash, sdash in enumerate(ver_dash_split):
                for el in _split_alpha_num(sdash):
                    ver_split.append(el)

                if idash < n_dash - 1:
                    ver_split.append("-")

            if iunder < n_under - 1:
                ver_split.append("_")

        if idot < n_dot - 1:
            ver_split.append(".")

    def _yield_splits_from_index(start, ver_split_start, num_bump):
        if start < len(ver_split_start) and num_bump > 0:
            ver_split = copy.deepcopy(ver_split_start)
            for k in reversed(range(start, len(ver_split))):
                try:
                    t = int(ver_split[k])
                    is_num = True
                except Exception:
                    is_num = False

                if is_num:
                    for kk in range(num_bump):
                        ver_split[k] = str(t + 1 + kk)
                        yield "".join(ver_split)
                        yield from _yield_splits_from_index(
                            k + 1,
                            ver_split,
                            num_bump - 1,
                        )
                    ver_split[k] = "0"
                elif (
                    increment_alpha
                    and ver_split[k].isalpha()
                    and len(ver_split[k]) == 1
                ):
                    for kk in range(num_bump):
                        ver_split[k] = chr(ord(ver_split[k]) + 1)
                        yield "".join(ver_split)
                        yield from _yield_splits_from_index(
                            k + 1,
                            ver_split,
                            num_bump - 1,
                        )
                    ver_split[k] = "a"
                else:
                    continue

    for ver in _yield_splits_from_index(0, ver_split, 2):
        yield ver


class AbstractSource(abc.ABC):
    name: str

    @abc.abstractmethod
    def get_version(self, url: str, node_attrs: AttrsTypedDict) -> Optional[str]:
        """Get the version given a url.

        This method should catch all errors and return None if an
        error is caught. Logging statements at the DEBUG level
        can be added to help debug errors.

        The implementation should use the `is_version_ignored` function to ensure the
        returned version is not supposed to be ignored by the bot. If the version is
        ignored, return None if there are no other valid versions.

        Parameters
        ----------
        url
            The url used to find the version.
        node_attrs
            The feedstock node attributes.

        Returns
        -------
        version
            The version as a string or None if there is an error or the version is ignored.
        """
        pass

    @abc.abstractmethod
    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        """Get a url from which to fetch the latest version given the feedstock's
        node attributes.

        This method should catch all errors and return None if an
        error is caught. Logging statements at the DEBUG level
        can be added to help debug errors.

        Parameters
        ----------
        node_attrs
            The feedstock node attributes.

        Returns
        -------
        url
            The url to pass to get `get_version`. Returns None if there is an
            error.
        """
        pass


class VersionFromFeed(AbstractSource, abc.ABC):
    name = "VersionFromFeed"
    ver_prefix_remove = ["release-", "releases%2F", "v_", "v.", "v"]
    dev_vers = [
        "rc",
        "beta",
        "alpha",
        "dev",
        "a",
        "b",
        "init",
        "testing",
        "test",
        "pre",
        "git",
        "pc",
    ]

    def get_version(self, url: str, node_attrs: AttrsTypedDict) -> Optional[str]:
        data = feedparser.parse(url)
        if data["bozo"] == 1:
            return None
        vers = []

        for entry in data["entries"]:
            ver = urllib.parse.unquote(entry["link"]).split("/")[-1]

            if is_tag_ignored(node_attrs, ver):
                continue

            for prefix in self.ver_prefix_remove:
                if ver.startswith(prefix):
                    ver = ver[len(prefix) :]
            if any(s in ver.lower() for s in self.dev_vers):
                continue
            # Extract version number starting at the first digit.
            sval = re.search(r"(\d+[^\s]*)", ver)
            if sval is None:
                continue

            ver = sval.group(0)
            try:
                VersionOrder(ver.replace("-", "."))
            except Exception:
                continue

            if is_version_ignored(node_attrs, ver):
                continue

            vers.append(ver)
        if vers:
            return max(vers, key=lambda x: VersionOrder(x.replace("-", ".")))
        else:
            return None


class PyPI(AbstractSource):
    name = "PyPI"

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        url_names = ["pypi.python.org", "pypi.org", "pypi.io", "files.pythonhosted.org"]
        source_url = node_attrs.get("url", None)
        if source_url is None or (not any(s in source_url for s in url_names)):
            return None
        if "files.pythonhosted.org" in source_url:
            pkg = node_attrs["url"].split("/")[-1].rsplit("-", maxsplit=1)[0]
        else:
            pkg = node_attrs["url"].split("/")[6]
        return f"https://pypi.org/pypi/{pkg}/json"

    def get_version(self, url: str, node_attrs: AttrsTypedDict) -> Optional[str]:
        r = requests.get(url)
        # If it is a pre-release don't give back the pre-release version
        if not r.ok:
            return None

        try:
            jblob = r.json()
        except Exception:
            return None

        if "info" not in jblob or "version" not in jblob["info"]:
            return None

        most_recent_version = jblob["info"]["version"].strip()
        if parse_version(most_recent_version).is_prerelease:
            # if ALL releases are prereleases return the version
            if not all(parse_version(v).is_prerelease for v in r.json()["releases"]):
                return None

        if is_version_ignored(node_attrs, most_recent_version):
            return None

        return most_recent_version


class NPM(AbstractSource):
    name = "NPM"

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        source_url = node_attrs.get("url", None)
        if source_url is None or "registry.npmjs.org" not in source_url:
            return None
        # might be namespaced
        pkg = source_url.split("/")[3:-2]
        return f"https://registry.npmjs.org/{'/'.join(pkg)}"

    def get_version(self, url: str, node_attrs: AttrsTypedDict) -> Optional[str]:
        r = requests.get(url)
        if not r.ok:
            return None
        latest = r.json()["dist-tags"].get("latest", "").strip()
        # If it is a pre-release don't give back the pre-release version
        if (
            not len(latest)
            or parse_version(latest).is_prerelease
            or is_version_ignored(node_attrs, latest)
        ):
            return None

        return latest


class CRAN(AbstractSource):
    """The CRAN versions source.

    Uses a local CRAN index instead of one request per package.

    The index is lazy initialized on first `get_url` call and kept in
    memory on module level as `CRAN_INDEX` like a singleton. This way it
    is shared on executor level and not serialized with every instance of
    the CRAN class to allow efficient distributed execution with e.g.
    dask.
    """

    name = "CRAN"
    url_contains = "cran.r-project.org/src/contrib/Archive"
    cran_url = "https://cran.r-project.org"

    def init(self) -> None:
        global CRAN_INDEX
        if not CRAN_INDEX:
            try:
                session = requests.Session()
                CRAN_INDEX = self._get_cran_index(session)
                logger.debug("Cran source initialized")
            except Exception:
                logger.exception("Cran initialization failed")
                CRAN_INDEX = {}

    def _get_cran_index(self, session: requests.Session) -> dict:
        # from conda_build/skeletons/cran.py:get_cran_index
        logger.debug("Fetching cran index from %s", self.cran_url)
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

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        self.init()
        urls = node_attrs.get("url", None)
        if urls is None:
            return None
        if not isinstance(node_attrs["url"], list):
            urls = [urls]
        for url in urls:
            if self.url_contains not in url:
                continue
            # alternatively: pkg = node_attrs["name"].split("r-", 1)[-1]
            pkg = url.split("/")[6].lower()
            if pkg in CRAN_INDEX:
                return CRAN_INDEX[pkg]
            else:
                return None
        return None

    def get_version(self, url: str, node_attrs: AttrsTypedDict) -> Optional[str]:
        if not url[1]:
            return None

        ver = str(url[1]).replace("-", "_")
        if is_version_ignored(node_attrs, ver):
            return None

        return ver


ROS_DISTRO_INDEX: Optional[dict] = None


class ROSDistro(AbstractSource):
    name = "ROSDistro"

    def parse_idx(self, distro_name: str = "melodic") -> dict:
        session = requests.Session()
        res = session.get(
            f"https://raw.githubusercontent.com/ros/rosdistro/master/{distro_name}/distribution.yaml",  # noqa
        )
        res.raise_for_status()
        resd = yaml.safe_load(res.text)
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
                logger.exception("ROS Distro initialization failed")
                ROS_DISTRO_INDEX = {}

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        if not node_attrs["name"].startswith("ros-"):
            return None

        self.init()

        toplevel_package, package = ROS_DISTRO_INDEX["melodic"]["reverse"][
            node_attrs["name"]
        ]

        p_dict = ROS_DISTRO_INDEX["melodic"]["forward"][toplevel_package]
        version = p_dict["release"]["version"]
        tag_url = p_dict["release"]["tags"]["release"].format(
            package=package,
            version=version,
        )
        url = p_dict["release"]["url"]

        if url.endswith(".git"):
            url = url[:-4]

        final_url = f"{url}/archive/{tag_url}.tar.gz"
        self.version_url_cache[final_url] = version.split("-")[0]

        return final_url

    def get_version(self, url: str, node_attrs: AttrsTypedDict):
        ver = self.version_url_cache[url]

        if is_version_ignored(node_attrs, ver):
            return None

        return ver


def get_sha256(url: str) -> Optional[str]:
    try:
        return hash_url(url, timeout=120, hash_type="sha256")
    except Exception as e:
        logger.debug("url hashing exception: %s", repr(e))
        return None


def url_exists(url: str, timeout: int | float = 5) -> bool:
    """
    We use curl/wget here, as opposed requests.head, because
     - github urls redirect with a 3XX code even if the file doesn't exist
     - requests cannot handle ftp.
    """
    url_exists = False
    if not url_exists:
        try:
            subprocess.run(
                ["curl", "-fsLI", url],
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.debug("url_exists curl exception", exc_info=e)
            url_exists = False
        else:
            url_exists = True

    if not url_exists:
        try:
            output = subprocess.check_output(
                ["wget", "--spider", url],
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        except Exception as e:
            logger.debug("url_exists wget exception", exc_info=e)
            url_exists = False
        else:
            # For FTP servers an exception is not thrown
            if "No such file" in output.decode("utf-8"):
                url_exists = False
            elif "not retrieving" in output.decode("utf-8"):
                url_exists = False
            else:
                url_exists = True

    return url_exists


def url_exists_swap_exts(url: str):
    if url_exists(url):
        return True, url

    # TODO this is too expensive
    # from conda_forge_tick.url_transforms import gen_transformed_urls
    # for new_url in gen_transformed_urls(url):
    #     if url_exists(new_url):
    #         return True, new_url

    return False, None


class BaseRawURL(AbstractSource):
    name = "BaseRawURL"
    next_ver_func = None

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        if "feedstock_name" not in node_attrs:
            return None
        if "version" not in node_attrs:
            return None

        content = node_attrs["raw_meta_yaml"]

        # get a ci_support pinning file if we have one
        ci_support_keys = set()
        for key in node_attrs.keys():
            if key.startswith("ci_support_"):
                ci_support_keys.add(key)
        if ci_support_keys:
            ci_support_key = sorted(ci_support_keys)[0]
            plat, arch = get_platform_arch_from_ci_support_filename(
                ci_support_key.replace("ci_support", "")
            )
            platform_arch = f"{plat}-{arch}"
            cbc_data = node_attrs[ci_support_key]
        else:
            platform_arch = None
            cbc_data = None

        if any(ln.startswith("{% set version") for ln in content.splitlines()):
            has_version_jinja2 = True
        else:
            has_version_jinja2 = False

        # this while statement runs until a bad version is found
        # then it uses the previous one
        orig_urls = urls_from_meta(node_attrs["meta_yaml"])
        logger.debug("orig urls: %s", orig_urls)
        current_ver = node_attrs["version"]
        current_sha256 = None
        orig_ver = current_ver
        found = True
        count = 0
        max_count = 10

        while found and count < max_count:
            found = False
            for next_ver in self.next_ver_func(current_ver):
                logger.debug("trying version: %s", next_ver)

                if is_version_ignored(node_attrs, next_ver):
                    logger.debug("version is ignored - skipping!")
                    continue

                if has_version_jinja2:
                    _new_lines = []
                    for ln in content.splitlines():
                        if ln.startswith("{% set version ") or ln.startswith(
                            "{% set version=",
                        ):
                            _new_lines.append('{%% set version = "%s" %%}' % next_ver)
                        else:
                            _new_lines.append(ln)
                    new_content = "\n".join(_new_lines)
                else:
                    new_content = content.replace(orig_ver, next_ver)
                if node_attrs["meta_yaml"].get("schema_version", 0) == 0:
                    new_meta = parse_meta_yaml(new_content)
                else:
                    new_meta = parse_recipe_yaml(
                        new_content, platform_arch=platform_arch, cbc_path=cbc_data
                    )
                new_urls = urls_from_meta(new_meta)
                if len(new_urls) == 0:
                    logger.debug("No URL in meta.yaml")
                    return None

                logger.debug("parsed new version: %s", new_meta["package"]["version"])
                url_to_use = None
                for url in urls_from_meta(new_meta):
                    # this URL looks bad if these things happen
                    if (
                        str(new_meta["package"]["version"]) != next_ver
                        or node_attrs.get("url", "") == url
                        or url in orig_urls
                    ):
                        logger.debug(
                            "skipping url '%s' due to "
                            "\n    %s = %s\n    %s = %s\n    %s = %s",
                            url,
                            'str(new_meta["package"]["version"]) != next_ver',
                            str(new_meta["package"]["version"]) != next_ver,
                            'meta_yaml["url"] == url',
                            node_attrs.get("url", "") == url,
                            "url in orig_urls",
                            url in orig_urls,
                        )
                        continue

                    logger.debug("trying url: %s", url)
                    _exists, _url_to_use = url_exists_swap_exts(url)
                    if not _exists:
                        logger.debug(
                            "version %s does not exist for url %s",
                            next_ver,
                            url,
                        )
                        continue
                    else:
                        url_to_use = _url_to_use

                if url_to_use is not None:
                    found = True
                    count = count + 1
                    current_ver = next_ver
                    new_sha256 = get_sha256(url_to_use)
                    if new_sha256 is None:
                        logger.debug(
                            "skipping url %s because it did not has",
                            url_to_use,
                        )
                        return None

                    if new_sha256 == current_sha256 or new_sha256 in new_content:
                        logger.debug(
                            "skipping url %s because it returned the same hash",
                            url_to_use,
                        )
                        return None
                    current_sha256 = new_sha256
                    logger.debug("version %s is ok for url %s", current_ver, url_to_use)
                    break

        if current_ver != orig_ver:
            logger.debug("using version %s", current_ver)
            return current_ver

        return None

    def get_version(self, url: str, node_attrs: AttrsTypedDict) -> str:
        return url


class RawURL(BaseRawURL):
    name = "RawURL"
    next_ver_func = functools.partial(next_version, increment_alpha=False)


class IncrementAlphaRawURL(BaseRawURL):
    name = "IncrementAlphaRawURL"
    next_ver_func = functools.partial(next_version, increment_alpha=True)
    feedstock_ok_list = ["openssl", "tzcode", "tzdata", "jpeg", "cddlib"]

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        if "feedstock_name" not in node_attrs:
            return None

        if node_attrs["feedstock_name"] not in self.feedstock_ok_list:
            return None

        return super().get_url(node_attrs)


class GitTags(AbstractSource):
    name = "GitTags"

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        return node_attrs.get("meta_yaml", {}).get("source", {}).get("git_url", None)

    def get_version(self, url: str, node_attrs: AttrsTypedDict) -> Optional[str]:
        try:
            output = subprocess.check_output(
                ["git", "ls-remote", "--tags", url], text=True
            )
        except Exception:
            return None
        # Output looks like this, and we only want '25.7.0'
        # 6614653b1d9bdbffcef55e338d3220daed70c7f8        refs/tags/25.7.0
        versions = []
        for line in output.splitlines():
            if not line.strip():
                continue
            fields = line.split(None, 1)
            if len(fields) != 2:
                continue
            tag = fields[1]

            if is_tag_ignored(node_attrs, tag):
                continue

            # we will strip everything before the first digit
            first_digit = next((i for i, c in enumerate(tag) if c.isdigit()), None)
            if first_digit is None:
                continue
            version = tag[first_digit:].replace("-", ".")
            try:
                VersionOrder(version)
            except Exception:
                continue

            if is_version_ignored(node_attrs, version):
                continue

            versions.append(version)

        if versions:
            return max(versions, key=VersionOrder)
        return None


class Github(VersionFromFeed):
    name = "Github"
    version_prefix = None

    def set_version_prefix(self, version: str, split_url: list[str]):
        self.version_prefix = self.get_version_prefix(version, split_url)
        if self.version_prefix is None:
            return
        logger.debug("Found version prefix from url: %s", self.version_prefix)
        self.ver_prefix_remove = [self.version_prefix] + self.ver_prefix_remove

    def get_version_prefix(self, version: str, split_url: list[str]):
        """Return prefix for the first split that contains version. If prefix
        is empty - returns None.
        """
        r = re.compile(rf"^(.*){version}")
        for split in split_url:
            match = r.match(split)
            if match is not None:
                if match.group(1) == "":
                    return None
                return match.group(1)

        return None

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        source_url = node_attrs.get("url", None)
        if source_url is None or "github.com" not in source_url:
            return None
        split_url = source_url.lower().split("/")
        version = node_attrs["version"]
        self.set_version_prefix(version, split_url)
        package_owner = split_url[split_url.index("github.com") + 1]
        gh_package_name = split_url[split_url.index("github.com") + 2]
        return f"https://github.com/{package_owner}/{gh_package_name}/releases.atom"


class GithubReleases(AbstractSource):
    name = "GithubReleases"

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        source_url = node_attrs.get("url", None)
        if source_url is None or "github.com" not in source_url:
            return None
        # might be namespaced
        owner, repo = source_url.split("/")[3:5]
        return f"https://github.com/{owner}/{repo}/releases/latest"

    def get_version(self, url: str, node_attrs: AttrsTypedDict) -> Optional[str]:
        r = requests.get(url)
        if not r.ok:
            return None
        # "/releases/latest" redirects to "/releases/tag/<tag name>"
        url_components = r.url.split("/")
        latest = "/".join(url_components[url_components.index("releases") + 2 :])
        # If it is a pre-release don't give back the pre-release version
        try:
            if (
                len(latest) == 0
                or latest == "latest"
                or parse_version(latest).is_prerelease
            ):
                return None
        except InvalidVersion:
            # version strings violating the Python spec are supported
            pass

        if is_tag_ignored(node_attrs, latest):
            return None

        for prefix in ("v", "release-", "releases/"):
            if latest.startswith(prefix):
                latest = latest[len(prefix) :]
                break
        # Extract version number starting at the first digit.
        if match := re.search(r"(\d+[^\s]*)", latest):
            latest = match.group(0)

        if is_version_ignored(node_attrs, latest):
            return None

        return latest


# TODO: this one does not work because the atom feeds from libraries.io
# all return 403 and I cannot find the correct URL to use
# also url_contains is not defined
# also package_name is not defined
class LibrariesIO(VersionFromFeed):
    name = "LibrariesIO"

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        urls = node_attrs.get("url", None)
        if urls is None:
            return None
        if not isinstance(urls, list):
            urls = [urls]
        for url in urls:
            if self.url_contains not in url:
                continue
            pkg = self.package_name(url)
            return f"https://libraries.io/{self.name}/{pkg}/versions.atom"


class NVIDIA(AbstractSource):
    """Like BaseRawURL but it embeds logic based on NVIDIA's packaging schema."""

    name = "NVIDIA"

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        """Generate metadata needed to get the latest version of an NVIDIA redist.

        We actually return a URL plus other information needed to fetch the latest package
        version from "https://developer.download.nvidia.com/compute/{ compute_subdir
        }/redist/release_{ release_label }.json"

        We check a feedstock's conda-forge.yml for bot/version_updates/nvidia/compute_subdir
        and bot/version_updates/nvidia/json_name.

        "compute_subdir" is used as above to locate the correct redist folder, and
        json_name is used to find the correct section in the JSON. We expect the
        JSON to have the following format:

        ```json
        {
            "release_date": "2024-12-03",
            "release_label": "0.8.1",  # this is the same version used in the filename
            "release_product": "nvjpeg2000",
            "libnvjpeg_2k": {  # this is the key which corresponds to json_name
                "name": "NVIDIA nvJPEG 2000",
                "license": "nvJPEG 2K",
                "license_path": "libnvjpeg_2k/LICENSE.txt",
                "version": "0.8.1.40",
                ...
        }
        ```

        Each of "compute_subdir" and "json_name" will fallback to using the
        "feedstock-name" parameter if undefined.

        The returned url is not actually valid since we return the json slug that we need
        by separating it with #.
        """
        url = node_attrs.get("url", None)
        if url is None or "developer.download.nvidia.com/compute" not in url:
            logger.debug(
                "The source URL did not contain developer.download.nvidia.com/compute."
            )
            return None
        logger.debug("The source URL contains developer.download.nvidia.com/compute.")

        logger.debug("Searching for a NVIDIA URL compute_subdir.")
        nvidia_compute_subdir = get_keys_default(
            node_attrs,
            ["conda-forge.yml", "bot", "version_updates", "nvidia", "compute_subdir"],
            {},
            None,
        )
        if nvidia_compute_subdir is not None:
            logger.debug("Found explicit bot/version_updates/nvidia/compute_subdir.")
        elif "feedstock-name" in node_attrs["meta_yaml"]["extra"]:
            logger.debug("Found extra/feedstock-name.")
            nvidia_compute_subdir = node_attrs["meta_yaml"]["extra"]["feedstock-name"]
        else:
            logger.debug("Found the feedstock's name.")
            nvidia_compute_subdir = node_attrs["feedstock_name"]
        logger.debug("The compute_subdir for NVIDIA URL is %s.", nvidia_compute_subdir)

        logger.debug("Searching for a NVIDIA URL json_name.")
        nvidia_redist_json_name = get_keys_default(
            node_attrs,
            ["conda-forge.yml", "bot", "version_updates", "nvidia", "json_name"],
            {},
            None,
        )
        if nvidia_redist_json_name is not None:
            logger.debug("Found explicit bot/version_updates/nvidia/json_name.")
        elif "feedstock-name" in node_attrs["meta_yaml"]["extra"]:
            logger.debug("Found extra/feedstock-name.")
            nvidia_redist_json_name = node_attrs["meta_yaml"]["extra"]["feedstock-name"]
        else:
            logger.debug("Found the feedstock's name.")
            nvidia_redist_json_name = node_attrs["feedstock_name"]
        logger.debug("The json_name for NVIDIA URL is %s.", nvidia_redist_json_name)

        result = f"https://developer.download.nvidia.com/compute/{nvidia_compute_subdir}/redist#{nvidia_redist_json_name}"
        logger.debug("The NVIDIA redist URL should be %s", result)
        return result

    def get_version(self, url: str, node_attrs: AttrsTypedDict) -> Optional[str]:
        """Get latest version of a package by scraping nvidia.com JSONs.

        url should be an address of the following form: "https://developer.download.
        nvidia.com/compute/{nvidia_compute_subdir}/redist#{nvidia_redist_json_name}".
        where we expect 'https://developer.download.nvidia.com/compute/
        {{ nvidia_compute_subdir }}/redist/' to be a list of links which includes
        multiple 'redistrib_X.Y.Z.json'. The latest of which will be the nominal latest
        version. AND the string after # is the slug used to access the part of the JSON
        blob which is relevant to the package.

        Returns
        -------
            The full package version including build number.

        Raises
        ------
        KeyError
            If the slug is incorrect.
        """
        actual_url, slug = url.split("#")
        logger.debug("Searching %s for redistrib_X.Y.Z.json", actual_url)
        response = requests.get(actual_url)
        html_content = response.text
        # Search for links to redistrib_*.json in the response and strip the versions from there
        # re doesn't support repeating patterns, so we assume there are three version numbers
        redistrib_pattern = re.compile(
            pattern=r"redistrib_[0-9]+\.[0-9]+\.[0-9]+\.json<"
        )
        result = re.findall(redistrib_pattern, html_content)
        stripped_results = [x.removesuffix(".json<").split("_")[1] for x in result]
        stripped_results.sort(key=Version, reverse=True)
        logger.debug("Found the following NVIDIA release JSON: %s", stripped_results)
        if len(stripped_results) < 1:
            return None
        release_version = stripped_results[0]

        # Fetch library details from developer archive
        response = urllib.request.urlopen(
            f"{actual_url}/redistrib_{release_version}.json"
        )
        json_data = json.loads(response.read().decode("utf-8"))

        # Extract version from library details
        try:
            lib_info = json_data[slug]
        except KeyError as e:
            raise KeyError(
                "Please update bot/version_updates/nvidia/json_name in conda-forge.yml "
                "to a valid name in the JSON. "
                f"'{slug}' is not a valid source info blob in the release JSON."
            ) from e

        if is_version_ignored(node_attrs, lib_info["version"]):
            return None

        return lib_info["version"]


class CratesIO(AbstractSource):
    name = "CratesIO"

    def get_url(self, node_attrs: AttrsTypedDict) -> Optional[str]:
        source_url = node_attrs.get("url", None)
        if source_url is None or "crates.io" not in source_url:
            return None

        pkg = Path(source_url).parts[5]
        tier = self._tier_directory(pkg)

        return f"https://index.crates.io/{tier}"

    def get_version(self, url: str, node_attrs: AttrsTypedDict) -> Optional[str]:
        r = requests.get(url)

        if not r.ok:
            return None

        # the response body is a newline-delimited JSON stream, with the latest version
        # being the last line
        latest = orjson.loads(r.text.splitlines()[-1])

        ver = latest.get("vers")
        if ver is None:
            return None

        if is_version_ignored(node_attrs, ver):
            return None

        return latest.get("vers")

    @staticmethod
    def _tier_directory(package: str) -> str:
        """Depending on the length of the package name, the tier directory structure
        will differ.
        Documented here: https://doc.rust-lang.org/cargo/reference/registry-index.html#index-files.

        Raises
        ------
        ValueError
            If the package name is empty.
        """
        if not package:
            raise ValueError("Package name cannot be empty")

        name_len = len(package)

        if name_len <= 2:
            return f"{name_len}/{package}"
        elif name_len == 3:
            return f"{name_len}/{package[0]}/{package}"
        else:
            return f"{package[0:2]}/{package[2:4]}/{package}"
