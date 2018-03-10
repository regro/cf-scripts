import networkx as nx
import requests
from pkg_resources import parse_version
import feedparser
import os
import jinja2
import io
import ruamel.yaml
import subprocess

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


class NullUndefined(jinja2.Undefined):
    def __unicode__(self):
        return self._undefined_name

    def __getattr__(self, name):
        return '{}.{}'.format(self, name)

    def __getitem__(self, name):
        return '{}["{}"]'.format(self, name)


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


class RawURL:
    name = 'RawURL'
    def get_url(self, meta_yaml):
        pkg = meta_yaml['name']
        url_template = "https://raw.githubusercontent.com/conda-forge/{}-feedstock/master/recipe/meta.yaml"
        try:
            content = requests.get(url_template.format(pkg)).content
            content = content.decode('utf-8')
        except Exception:
            return None

        env = jinja2.Environment(undefined=NullUndefined)

        current_ver = meta_yaml['version']
        orig_ver = current_ver
        found = True
        while found:
            found = False
            for next_ver in next_version(current_ver):
                new_content = content.replace(orig_ver, next_ver)
                meta = ruamel.yaml.load(env.from_string(new_content).render(os=os), ruamel.yaml.RoundTripLoader)
                url = str(meta['source']['url'])
                if str(meta['package']['version']) != next_ver:
                    continue
                with open(os.devnull, 'w') as devnull:
                    try:
                        subprocess.check_call(["wget", "--spider", url], stdout=devnull, stderr=subprocess.STDOUT)
                    except:
                        continue
                    found = True
                    current_ver = next_ver
                    break
        if current_ver != orig_ver:
            return current_ver

    def get_version(self, url):
        return url


sources = [PyPI(), CRAN(), Github(), RawURL()]


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
                f.write('{}: Could not find version on {} at {}\n'.format(
                    meta_yaml['name'], source.name, url))
    with open('upstream_bad', 'a') as f:
        f.write('{}: unknown source at {}\n'.format(meta_yaml['name'],
                                                    meta_yaml['url']))
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
