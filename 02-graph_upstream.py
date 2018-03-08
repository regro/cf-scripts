import networkx as nx
import requests
from pkg_resources import parse_version
import feedparser

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
            return max(vers, key=lambda x:parse_version(x.replace('-','.')))
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
        return "https://github.com/{}/{}/releases.atom".format(package_owner, gh_package_name)


class LibrariesIO(VersionFromFeed):
    def get_url(self, meta_yaml):
        urls = meta_yaml['url']
        if not isinstance(meta_yaml['url'], list):
            urls = [urls]
        for url in urls:
            if not self.url_contains in url:
                continue
            pkg = self.package_name(url)
            return "https://libraries.io/{}/{}/versions.atom".format(self.name, pkg)


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


sources = [PyPI(), CRAN(), Github()]


def get_latest_version(meta_yaml):
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


# gx = nx.read_yaml('graph.yml')
gx = nx.read_gpickle('graph.pkl')

for node, attrs in gx.node.items():
    attrs['new_version'] = get_latest_version(attrs)
    print(node, attrs['version'], attrs['new_version'])

print('Current number of out of date packages not PRed: {}'.format(
    str(len([n for n, a in gx.node.items()
             if a['new_version']  # if we can get a new version
             and a['new_version'] != a['version']  # if we need a bump
             and a.get('PRed', '000') != a['new_version']  # if not PRed
             ]))))
print('writing out file')
del parse_version
# nx.write_yaml(gx, 'graph.yml')
nx.write_gpickle(gx, 'graph.pkl')
