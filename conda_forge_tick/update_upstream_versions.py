import os
import subprocess
import networkx as nx
import requests
from pkg_resources import parse_version
import feedparser
from .utils import parsed_meta_yaml

import logging

logger = logging.getLogger("conda_forge_tick.update_upstream_versions")


def next_version(ver):
    ver_split = []
    ver_dot_split = ver.split('.')
    for s in ver_dot_split:
        ver_dash_split = s.split('_')
        for j in ver_dash_split:
            ver_split.append(j)
            ver_split.append('_')
        ver_split[-1] = '.'
    del ver_split[-1]
    for j in reversed(range(len(ver_split))):
        try:
            t = int(ver_split[j])
        except:
            continue
        else:
            ver_split[j] = str(t + 1)
            yield ''.join(ver_split)
            ver_split[j] = '0'


class VersionFromFeed:
    ver_prefix_remove = ['release-', 'releases%2F', 'v']
    dev_vers = ['rc', 'beta', 'alpha', 'dev']

    def get_version(self, url):
        data = feedparser.parse(url)
        if data['bozo'] == 1:
            return None
        vers = []
        for entry in data['entries']:
            ver = entry['link'].split('/')[-1]
            for prefix in self.ver_prefix_remove:
                if ver.startswith(prefix):
                    ver = ver[len(prefix):]
            if any(s in ver for s in self.dev_vers):
                continue
            vers.append(ver)
        if vers:
            return max(vers, key=lambda x: parse_version(x.replace('-', '.')))
        else:
            return None


class Github(VersionFromFeed):
    name = 'github'

    def get_url(self, meta_yaml):
        if not 'github.com' in meta_yaml['url']:
            return
        split_url = meta_yaml['url'].lower().split('/')
        package_owner = split_url[split_url.index('github.com') + 1]
        gh_package_name = split_url[split_url.index('github.com') + 2]
        return "https://github.com/{}/{}/releases.atom".format(package_owner,
                                                               gh_package_name)


class LibrariesIO(VersionFromFeed):
    def get_url(self, meta_yaml):
        urls = meta_yaml['url']
        if not isinstance(meta_yaml['url'], list):
            urls = [urls]
        for url in urls:
            if not self.url_contains in url:
                continue
            pkg = self.package_name(url)
            return "https://libraries.io/{}/{}/versions.atom".format(self.name,
                                                                     pkg)


class PyPI:
    name = 'pypi'

    def get_url(self, meta_yaml):
        url_names = ['pypi.python.org', 'pypi.org', 'pypi.io']
        source_url = meta_yaml['url']
        if not any(s in source_url for s in url_names):
            return None
        pkg = meta_yaml['url'].split('/')[6]
        return 'https://pypi.org/pypi/{}/json'.format(pkg)

    def get_version(self, url):
        r = requests.get(url)
        if not r.ok:
            return False
        return r.json()['info']['version'].strip()


class CRAN(LibrariesIO):
    name = 'cran'
    url_contains = 'cran.r-project.org/src/contrib/Archive'
    package_name = lambda self, url: url.split('/')[6]

    def get_version(self, url):
        ver = LibrariesIO.get_version(self, url)
        return str(ver).replace('-', '_')


class RawURL:
    name = 'RawURL'

    def get_url(self, meta_yaml):
        pkg = meta_yaml['feedstock_name']
        url_template = "https://raw.githubusercontent.com/conda-forge/{}-feedstock/master/recipe/meta.yaml"
        try:
            content = requests.get(url_template.format(pkg)).content
            content = content.decode('utf-8')
        except Exception:
            return None

        current_ver = meta_yaml['version']
        orig_ver = current_ver
        found = True
        while found:
            found = False
            for next_ver in next_version(current_ver):
                new_content = content.replace(orig_ver, next_ver)
                meta = parsed_meta_yaml(new_content)
                url = str(meta['source']['url'])
                if str(meta['package']['version']) != next_ver:
                    continue
                with open(os.devnull, 'w') as devnull:
                    try:
                        subprocess.check_call(["wget", "--spider", url],
                                              stdout=devnull,
                                              stderr=subprocess.STDOUT)
                    except:
                        continue
                    found = True
                    current_ver = next_ver
                    break
        if current_ver != orig_ver:
            return current_ver

    def get_version(self, url):
        return url


def get_latest_version(meta_yaml, sources):
    logger.info('Getting upstream version for {}'.format(meta_yaml['name']))
    for source in sources:
        url = source.get_url(meta_yaml)
        if url is None:
            continue
        ver = source.get_version(url)
        if ver:
            return ver
        else:
            with open('upstream_bad', 'a') as f:
                f.write('{}: Could not find version on {}\n'.format(
                    meta_yaml['name'], source.name))
    with open('upstream_bad', 'a') as f:
        f.write('{}: unknown source\n'.format(meta_yaml['name']))
    return False


def update_upstream_versions(gx, sources=(PyPI(), CRAN(), Github(), RawURL())):
    for node, attrs in gx.node.items():
        attrs['new_version'] = get_latest_version(attrs, sources)
        print(node, attrs['version'], attrs['new_version'])

    logger.info('Current number of out of date packages not PRed: {}'.format(
        str(len([n for n, a in gx.node.items()
                 if a['new_version']  # if we can get a new version
                 and a['new_version'] != a['version']  # if we need a bump
                 and a.get('PRed', '000') != a['new_version']  # if not PRed
                 ]))))


def main(*args, **kwargs):
    logging.basicConfig(level=logging.ERROR)
    logger.setLevel(logging.INFO)

    logger.info('Reading graph')
    gx = nx.read_gpickle('graph.pkl')

    update_upstream_versions(gx)

    logger.info('writing out file')
    nx.write_gpickle(gx, 'graph.pkl')


if __name__ == "__main__":
    main()
