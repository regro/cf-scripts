import abc
import collections.abc
import re
import logging
import typing
import functools
from typing import (
    Optional,
    Set,
    Iterator,
    List,
)
import yaml
import feedparser
import requests
from conda.models.version import VersionOrder
from conda_forge_tick.utils import parse_meta_yaml
from .hashing import hash_url

# TODO: parse_version has bad type annotations
from pkg_resources import parse_version

if typing.TYPE_CHECKING:
    from conda_forge_tick.migrators_types import (
        MetaYamlTypedDict,
        SourceTypedDict,
    )


CRAN_INDEX: Optional[dict] = None

logger = logging.getLogger("conda_forge_tick._update_version.update_sources")


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

    for k in reversed(range(len(ver_split))):
        try:
            t = int(ver_split[k])
            is_num = True
        except Exception:
            is_num = False

        if is_num:
            ver_split[k] = str(t + 1)
            yield "".join(ver_split)
            ver_split[k] = "0"
        elif increment_alpha and ver_split[k].isalpha() and len(ver_split[k]) == 1:
            ver_split[k] = chr(ord(ver_split[k]) + 1)
            yield "".join(ver_split)
            ver_split[k] = "a"
        else:
            continue


class AbstractSource(abc.ABC):
    name: str

    @abc.abstractmethod
    def get_version(self, url: str) -> Optional[str]:
        pass

    @abc.abstractmethod
    def get_url(self, meta_yaml) -> Optional[str]:
        pass


class VersionFromFeed(AbstractSource):
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
    ]

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
            if any(s in ver.lower() for s in self.dev_vers):
                continue
            # Extract version number starting at the first digit.
            ver = re.search(r"(\d+[^\s]*)", ver).group(0)
            vers.append(ver)
        if vers:
            return max(vers, key=lambda x: VersionOrder(x.replace("-", ".")))
        else:
            return None


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
        return f"https://registry.npmjs.org/{'/'.join(pkg)}"

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

    The index is lazy initialized on first `get_url` call and kept in
    memory on module level as `CRAN_INDEX` like a singleton. This way it
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
                logger.debug("Cran source initialized")
            except Exception:
                logger.error("Cran initialization failed", exc_info=True)
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
            package=package,
            version=version,
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
        return hash_url(url, timeout=120, hash_type="sha256")
    except Exception as e:
        logger.debug("url hashing exception: %s", repr(e))
        return None


def url_exists(url: str) -> bool:
    """
    We use curl here, as opposed requests.head, because github urls redirect
    with a 3XX code even if the file doesn't exist.
    """
    try:
        requests.head(url, allow_redirects=True).raise_for_status()
    except requests.HTTPError:
        return False

    return True


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

    def get_url(self, meta_yaml) -> Optional[str]:
        if "feedstock_name" not in meta_yaml:
            return None
        if "version" not in meta_yaml:
            return None

        # TODO: pull this from the graph itself
        content = meta_yaml["raw_meta_yaml"]

        # this while statement runs until a bad version is found
        # then it uses the previous one
        orig_urls = urls_from_meta(meta_yaml["meta_yaml"])
        logger.debug("orig urls: %s", orig_urls)
        current_ver = meta_yaml["version"]
        current_sha256 = None
        orig_ver = current_ver
        found = True
        count = 0
        max_count = 10

        while found and count < max_count:
            found = False
            for next_ver in self.next_ver_func(current_ver):
                logger.debug("trying version: %s", next_ver)

                new_content = content.replace(orig_ver, next_ver)
                new_meta = parse_meta_yaml(new_content)
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
                        or meta_yaml["url"] == url
                        or url in orig_urls
                    ):
                        logger.debug(
                            "skipping url '%s' due to "
                            "\n    %s = %s\n    %s = %s\n    %s = %s",
                            url,
                            'str(new_meta["package"]["version"]) != next_ver',
                            str(new_meta["package"]["version"]) != next_ver,
                            'meta_yaml["url"] == url',
                            meta_yaml["url"] == url,
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
                    if new_sha256 == current_sha256 or new_sha256 in new_content:
                        return None
                    current_sha256 = new_sha256
                    logger.debug("version %s is ok for url %s", current_ver, url_to_use)
                    break

        if count == max_count:
            return None
        if current_ver != orig_ver:
            logger.debug("using version %s", current_ver)
            return current_ver
        return None

    def get_version(self, url: str) -> str:
        return url


class RawURL(BaseRawURL):
    name = "RawURL"
    next_ver_func = functools.partial(next_version, increment_alpha=False)


class IncrementAlphaRawURL(BaseRawURL):
    name = "IncrementAlphaRawURL"
    next_ver_func = functools.partial(next_version, increment_alpha=True)
    feedstock_ok_list = ["openssl", "tzcode", "tzdata", "jpeg", "cddlib"]

    def get_url(self, meta_yaml) -> Optional[str]:
        if "feedstock_name" not in meta_yaml:
            return None

        if meta_yaml["feedstock_name"] not in self.feedstock_ok_list:
            return None

        return super().get_url(meta_yaml)


class Github(VersionFromFeed):
    name = "github"

    def get_url(self, meta_yaml) -> Optional[str]:
        if "github.com" not in meta_yaml["url"]:
            return None
        split_url = meta_yaml["url"].lower().split("/")
        package_owner = split_url[split_url.index("github.com") + 1]
        gh_package_name = split_url[split_url.index("github.com") + 2]
        return f"https://github.com/{package_owner}/{gh_package_name}/releases.atom"


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
