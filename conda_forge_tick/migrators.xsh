"""Classes for migrating repos"""
import os
import urllib.error

import re
import networkx as nx
from conda.models.version import VersionOrder
from rever.tools import (eval_version, indir, hash_url, replace_in_file)

from .utils import render_meta_yaml, UniversalSet


class Migrator:
    """Base class for Migrators"""
    rerender = False

    migrator_version = 0

    def __init__(self, pr_limit=0):
        self.pr_limit = pr_limit

    def filter(self, attrs):
        """ If true don't act upon node

        Parameters
        ----------
        attrs : dict
            The node attributes

        Returns
        -------
        bool :
            True if node is to be skipped
        """
        # never run on archived feedstocks
        # don't run on things we've already done
        # don't run on bad nodes
        return (attrs.get('archived', False)
                or self.migrator_uid(attrs) in attrs.get('PRed', [])
                or attrs.get('bad', False))

    def migrate(self, recipe_dir, attrs, **kwargs):
        """Perform the migration, updating the ``meta.yaml``

        Parameters
        ----------
        recipe_dir : str
            The directory of the recipe
        attrs : dict
            The node attributes

        Returns
        -------
        namedtuple or bool:
            If namedtuple continue with PR, if False scrap local folder
        """
        return self.migrator_uid(attrs)

    def pr_body(self):
        """Create a PR message body

        Returns
        -------
        body: str
            The body of the PR message
        """
        body = (
            '{}\n'
            '<sub>'
            'This PR was created by the [cf-regro-autotick-bot](https://github.com/regro/cf-scripts).\n'
            'The **cf-regro-autotick-bot** is a service to automatically '
            'track the dependency graph, migrate packages, and '
            'propose package version updates for conda-forge. '
            "If you would like a local version of this bot, you might consider using "
            "[rever](https://regro.github.io/rever-docs/). "
            "Rever is a tool for automating software releases and forms the "
            "backbone of the bot's conda-forge PRing capability. Rever is both "
            "conda (`conda install -c conda-forge rever`) and pip "
            "(`pip install re-ver`) installable.\n"
            'Finally, feel free to drop us a line if there are any '
            '[issues](https://github.com/regro/cf-scripts/issues)!'
            '</sub>')
        return body

    def commit_message(self):
        """Create a commit message"""
        return 'migration: ' + self.__class__.__name__

    def pr_title(self):
        """Title for PR"""
        return 'PR from Regro-cf-autotick-bot'

    def pr_head(self):
        """Head for PR"""
        return $USERNAME + ':' + self.remote_branch()

    def remote_branch(self):
        """Branch to use on local and remote"""
        return 'bot-pr'

    def migrator_uid(self, attrs):
        """Make a unique id for this migrator and node attrs

        Parameters
        ----------
        attrs: dict
            Node attrs

        Returns
        -------
        nt: namedtuple
            The unique id as a namedtuple
        """
        return {'migrator_name': self.__class__.__name__,
                'migrator_version': self.migrator_version}


class Version(Migrator):
    """Migrator for version bumping of packages"""
    patterns = (
        # filename, pattern, new
        # set the version
        ('meta.yaml', 'version:\s*[A-Za-z0-9._-]+', 'version: "$VERSION"'),
        ('meta.yaml', '{%\s*set\s+version\s*=\s*[^\s]*\s*%}',
            '{% set version = "$VERSION" %}'),
        # reset the build number to 0
        ('meta.yaml', '  number:\s*[0-9]+', '  number: 0'),
        ('meta.yaml', '{%\s*set build_number\s*=\s*"?[0-9]+"?\s*%}',
         '{% set build_number = 0 %}'),
        ('meta.yaml', '{%\s*set build\s*=\s*"?[0-9]+"?\s*%}',
         '{% set build = 0 %}'),
    )

    url_pat = re.compile(r'^( *)(-)?(\s*)url:\s*([^\s#]+?)\s*(?:(#.*)?\[([^\[\]]+)\])?(?(5)[^\(\)\n]*)(?(2)\n\1 \3.*)*$', flags=re.M)
    r_url_pat = re.compile(r'^(\s*)(-)?(\s*)url:\s*(?:(#.*)?\[([^\[\]]+)\])?(?(4)[^\(\)]*?)\n(\1(?(2) \3)  -.*\n?)*', flags=re.M)
    r_urls = re.compile('\s*-\s*(.+?)(?:#.*)?$', flags=re.M)

    migrator_version = 0

    def find_urls(self, text):
        """Get the URLs and platforms in a meta.yaml."""
        urls = []
        for m in self.url_pat.finditer(text):
            urls.append((m.group(4), m.group(6), m.group()))
        for m in self.r_url_pat.finditer(text):
            if m is not None:
                r = self.r_urls.findall(m.group())
                urls.append((r, m.group(2), m.group()))
        return urls

    def get_hash_patterns(self, filename, urls, hash_type):
        """Get the patterns to replace hash for each platform."""
        pats = ()
        checksum_names = ['hash_value', 'hash', 'hash_val', 'sha256sum',
                          'checksum', hash_type]
        for url, platform, line in urls:
            if isinstance(url, list):
                for u in url:
                    u = u.strip("'\"")
                    try:
                        hash = hash_url(u, hash_type)
                        break
                    except urllib.error.HTTPError:
                        continue
            else:
                url = url.strip("'\"")
                hash = hash_url(url, hash_type)
            m = re.search('\s*{}:(.+)'.format(hash_type), line)
            if m is None:
                p = '{}:\s*[0-9A-Fa-f]+'.format(hash_type)
                if platform:
                    p += '\s*(#.*)\[{}\](?(1)[^\(\)]*)$'.format(platform)
                else:
                    p += '$'
            else:
                p = '{}:{}$'.format(hash_type, m.group(1))
            n = '{}: {}'.format(hash_type, hash)
            if platform:
                n += '  # [{}]'.format(platform)
            pats += ((filename, p, n),)

            base1 = '''{{%\s*set {checkname} = ['"][0-9A-Fa-f]+['"] %}}'''
            base2 = '{{% set {checkname} = "{h}" %}}'
            for cn in checksum_names:
                pats += (('meta.yaml',
                          base1.format(checkname=cn),
                          base2.format(checkname=cn, h=hash)),)
        return pats

    def filter(self, attrs):
        # if no new version do nothing
        if "new_version" not in attrs:
            return True
        conditional = super().filter(attrs)
        return bool(
            conditional  # if archived/finished
            or not attrs.get('new_version')  # if no new version
            # if new version is less than current version
            or (VersionOrder(str(attrs['new_version'])) <=
                VersionOrder(str(attrs['version'])))
            # if PRed version is greater than newest version
            or any(VersionOrder(self._extract_version_from_hash(h)) >=
                   VersionOrder(attrs['new_version']
                                ) for h in attrs.get('PRed', set())))

    def migrate(self, recipe_dir, attrs, hash_type='sha256'):
        # Render with new version but nothing else
        version = attrs['new_version']
        with indir(recipe_dir):
            with open('meta.yaml', 'r') as f:
                text = f.read()
        url = re.search('\s*-?\s*url:.*?\n(    -.*\n?)*', text).group()
        if 'cran.r-project.org/src/contrib' in url:
            version = version.replace('_', '-')
        with indir(recipe_dir), ${...}.swap(VERSION=version):
            for f, p, n in self.patterns:
                p = eval_version(p)
                n = eval_version(n)
                replace_in_file(p, n, f)
            with open('meta.yaml', 'r') as f:
                text = f.read()

        # Get patterns to replace checksum for each platform
        rendered_text = render_meta_yaml(text)
        urls = self.find_urls(rendered_text)
        new_patterns = self.get_hash_patterns('meta.yaml', urls, hash_type)

        with indir(recipe_dir):
            for f, p, n in new_patterns:
                p = eval_version(p)
                n = eval_version(n)
                replace_in_file(p, n, f)
        return self.migrator_uid(attrs)

    def pr_body(self):
        pred = [(name, $SUBGRAPH.node[name]['new_version'])
                for name in list($SUBGRAPH.predecessors($NODE))]
        body = super().pr_body()
        body = body.format(
            'It is very likely that the current package version for this '
            'feedstock is out of date.\n'
            'Notes and instructions for merging this PR:\n'
            '1. Please check that the dependencies have not changed. \n'
            '2. Please merge the PR only after the tests have passed. \n'
            "3. Feel free to push to the bot's branch to update this PR if needed. \n"
            "4. The bot will almost always only open one PR per version. \n\n")
        # Statement here
        template = ('|{name}|{new_version}|[![Anaconda-Server Badge]'
                    '(https://img.shields.io/conda/vn/conda-forge/{name}.svg)]'
                    '(https://anaconda.org/conda-forge/{name})|\n')
        if len(pred) > 0:
            body += ('\n\nHere is a list of all the pending dependencies (and their '
                     'versions) for this repo. '
                     'Please double check all dependencies before merging.\n\n')
            # Only add the header row if we have content.
            # Otherwise the rendered table in the github comment
            # is empty which is confusing
            body += ('| Name | Upstream Version | Current Version |\n'
                     '|:----:|:----------------:|:---------------:|\n')
        for p in pred:
            body += template.format(name=p[0], new_version=p[1])
        return body

    def commit_message(self):
        return "updated v" + self.attrs['new_version']

    def pr_title(self):
        return $PROJECT + ' v' + self.attrs['new_version']

    def pr_head(self):
        return $USERNAME + ':' + self.remote_branch()

    def remote_branch(self):
        return self.attrs['new_version']

    def migrator_uid(self, attrs):
        n = super().migrator_uid(attrs)
        n.update({'version': attrs["new_version"]})
        return n

    def _extract_version_from_hash(self, h):
        return h.get('version', '0.0.0')


class JS(Migrator):
    """Migrator for JavaScript syntax"""
    patterns = [
        ('meta.yaml', '  script: npm install -g \.',
         '  script: |\n'
         '    tgz=$(npm pack)\n'
         '    npm install -g $tgz'),
        ('meta.yaml', '   script: |\n', '  script: |')
    ]

    migrator_version = 0

    def filter(self, attrs):
        conditional = super().filter(attrs)
        return bool(conditional or
                ((attrs.get('meta_yaml', {})
                .get('build', {})
                .get('noarch') != 'generic')
                or (attrs.get('meta_yaml', {})
                    .get('build', {})
                    .get('script') != 'npm install -g .'))
                and '  script: |' in attrs.get('raw_meta_yaml', '').split('\n')
                    )

    def migrate(self, recipe_dir, attrs, **kwargs):
        with indir(recipe_dir):
            for f, p, n in self.patterns:
                p = eval_version(p)
                n = eval_version(n)
                replace_in_file(p, n, f,
                                leading_whitespace=False
                                )
            Rebuild.bump_build_number('meta.yaml')
        return self.migrator_uid(attrs)

    def pr_body(self):
        body = super().pr_body()
        body = body.format(
            'It is very likely that this feedstock is in need of migration.\n'
            'Notes and instructions for merging this PR:\n'
            '1. Please merge the PR only after the tests have passed. \n'
            "2. Feel free to push to the bot's branch to update this PR if needed. \n")
        return body

    def commit_message(self):
        return "migrated to new npm build"

    def pr_title(self):
        return 'Migrate to new npm build'

    def pr_head(self):
        return $USERNAME + ':' + self.remote_branch()

    def remote_branch(self):
        return 'npm_migration'


class Compiler(Migrator):
    """Migrator for Jinja2 comiler syntax."""
    migrator_version = 0

    rerender = True

    compilers = {'toolchain', 'gcc', 'cython'}

    def filter(self, attrs):
        for req in attrs.get('req', []):
            if req.endswith('_compiler_stub') or req == 'r-base':
                return True
        conditional = super().filter(attrs)  
        return (conditional or not any(x in attrs.get('req', []) for x in self.compilers))

    def migrate(self, recipe_dir, attrs, **kwargs):
        self.out = $(conda-smithy update-cb3 --recipe_directory @(recipe_dir))
        with indir(recipe_dir):
            Rebuild.bump_build_number('meta.yaml')
        return self.migrator_uid(attrs)

    def pr_body(self):
        body = super().pr_body()
        body = body.format('{}\n'
                    '*If you have recived a `Migrate to Jinja2 compiler '
                    'syntax` PR from me recently please close that one and use '
                    'this one*.\n'
                    'It is very likely that this feedstock is in need of migration.\n'
                    'Notes and instructions for merging this PR:\n'
                    '1. Please merge the PR only after the tests have passed. \n'
                    "2. Feel free to push to the bot's branch to update this PR if needed. \n"
                    "3. If this recipe has a `cython` dependency please note that only a `C`"
                    " compiler has been added. If the project also needs a `C++` compiler"
                    " please add it by adding `- {{ compiler('cxx') }}` to the build section \n"
                    .format(self.out))
        return body

    def commit_message(self):
        return "migrated to Jinja2 compiler syntax build"

    def pr_title(self):
        return 'Migrate to Jinja2 compiler syntax'

    def pr_head(self):
        return $USERNAME + ':' + self.remote_branch()

    def remote_branch(self):
        return 'compiler_migration2'


class Noarch(Migrator):
    """Migrator for adding noarch."""
    migrator_version = 0

    compiler_pat = re.compile('.*_compiler_stub')
    sel_pat = re.compile('(.+?)\s*(#.*)?\[([^\[\]]+)\](?(2)[^\(\)]*)$')
    unallowed_reqs = ['toolchain', 'gcc', 'cython', 'clangdev']
    checklist = ['No compiled extensions',
                 'No post-link or pre-link or pre-unlink scripts',
                 'No OS specific build scripts',
                 'No python version specific requirements',
                 'No skips except for python version. (If the recipe is py3 only, remove skip statement and add version constraint on python)',
                 '2to3 is not used',
                 'Scripts argument in setup.py is not used',
                 'If entrypoints are in setup.py, they are listed in meta.yaml',
                 'No activate scripts',
                 'Not a dependency of `conda`',
                ]

    rerender = True

    def filter(self, attrs):
        conditional = (super().filter(attrs) or
                       attrs.get('meta_yaml', {}).get('outputs') or
                       attrs.get('meta_yaml', {}).get('build', {}).get('noarch')
                      )
        if conditional:
            return True
        python = False
        for req in attrs.get('req', []):
            if self.compiler_pat.match(req) or req in self.unallowed_reqs:
                return True
            if req == 'python':
                python = True
        if not python:
            return True
        for line in attrs.get('raw_meta_yaml', '').splitlines():
            if self.sel_pat.match(line):
                return True

        # Not a dependency of `conda`
        if attrs['feedstock_name'] in nx.ancestors($GRAPH, 'conda'):
            return True

        return False

    def migrate(self, recipe_dir, attrs, **kwargs):
        with indir(recipe_dir):
            build_idx = [l.rstrip() for l in
                         attrs['raw_meta_yaml'].split('\n')].index('build:')
            line = attrs['raw_meta_yaml'].split('\n')[build_idx + 1]
            spaces = len(line) - len(line.lstrip())
            replace_in_file(
                'build:',
                'build:\n{}noarch: python'.format(' '*spaces),
                'meta.yaml',
                leading_whitespace=False)
            replace_in_file(
                    'script:.+?',
                    'script: python -m pip install --no-deps --ignore-installed .',
                    'meta.yaml')
            replace_in_file(
                '  build:',
                '  host:',
                'meta.yaml',
                leading_whitespace=False)
            if 'pip' not in attrs['req']:
                replace_in_file(
                        '  host:',
                        '  host:\n    - pip',
                        'meta.yaml',
                        leading_whitespace=False)
            Rebuild.bump_build_number('meta.yaml')
        return self.migrator_uid(attrs)

    def pr_body(self):
        body = super().pr_body()
        body = body.format(
                    'I think this feedstock could be built with noarch.\n'
                    'This means that the package only needs to be built '
                    'once, drastically reducing CI usage.\n'
                    'See [here](https://conda-forge.org/docs/meta.html#building-noarch-packages) '
                    'for more information about building noarch packages.\n'
                    'Before merging this PR make sure:\n{}\n'
                    'Notes and instructions for merging this PR:\n'
                    '1. If any items in the above checklist are not satisfied, '
                    'please close this PR. Do not merge. \n'
                    '2. Please merge the PR only after the tests have passed. \n'
                    "3. Feel free to push to the bot's branch to update this PR if needed. \n"
                    )
        body = body.format('\n'.join(['- [ ] ' + item for item in self.checklist]))
        return body

    def commit_message(self):
        return "add noarch"

    def pr_title(self):
        return 'Suggestion: add noarch'

    def pr_head(self):
        return $USERNAME + ':' + self.remote_branch()

    def remote_branch(self):
        return 'noarch_migration'


class Rebuild(Migrator):
    """Migrator for bumping the build number."""
    migrator_version = 0
    rerender = True

    build_patterns = ((re.compile('(\s*?)number:\s*([0-9]+)'),
                       'number: {}'),
                      (re.compile('(\s*?){%\s*set build_number\s*=\s*"?([0-9]+)"?\s*%}'),
                       '{{% set build_number = {} %}}'),
                      (re.compile('(\s*?){%\s*set build\s*=\s*"?([0-9]+)"?\s*%}'),
                       '{{% set build = {} %}}')
                     )

    def __init__(self, graph, pr_limit=0):
        super().__init__(pr_limit)
        self.graph = graph
    
    @classmethod
    def bump_build_number(cls, filename):
        """Bump the build number of the specified recipe.

        Parameters
        ----------
        filename : str
            Path the the meta.yaml

        """

        for p, n in cls.build_patterns:
            with open(filename, 'r') as f:
                raw = f.read()
            lines = raw.splitlines()
            for i, line in enumerate(lines):
                m = p.match(line)
                if m is not None:
                    lines[i] = m.group(1) + n.format(int(m.group(2)) + 1)
            upd = '\n'.join(lines) + '\n'
            with open(filename, 'w') as f:
                f.write(upd)

    def filter(self, attrs):
        if attrs.get('archived', False) or attrs.get('bad', False):
            return True
        for node in self.graph.predecessors(attrs['feedstock_name']):
            att = self.graph.node[node]
            if self.migrator_uid(att) in att.get('PRed', []):
                return True
        return False

    def migrate(self, recipe_dir, attrs, **kwargs):
        with indir(recipe_dir):
            self.bump_build_number('meta.yaml')
        return self.migrator_uid(attrs)

    def pr_body(self):
        body = super().pr_body()
        body = body.format(
                    'It is likely this feedstock needs to be rebuilt.\n'
                    'Notes and instructions for merging this PR:\n'
                    '1. Please merge the PR only after the tests have passed. \n'
                    "2. Feel free to push to the bot's branch to update this PR if needed. \n"
                    )
        return body

    def commit_message(self):
        return "bump build number"

    def pr_title(self):
        return 'Rebuild'

    def pr_head(self):
        return $USERNAME + ':' + self.remote_branch()

    def remote_branch(self):
        return 'rebuild'


class Pinning(Migrator):
    """Migrator for remove pinnings for specified requirements."""
    migrator_version = 0
    rerender = True

    def __init__(self, pr_limit=0, removals=None):
        super().__init__(pr_limit)
        if removals == None:
            self.removals = UniversalSet()
        else:
            self.removals = set(removals)

    def filter(self, attrs):
        return (super().filter(attrs) or
                len(attrs.get("req", set()) & self.removals) == 0)

    def migrate(self, recipe_dir, attrs, **kwargs):
        remove_pins = attrs.get("req", set()) & self.removals
        remove_pats = {req: re.compile(f"\s*-\s*{req}.*?(\s+.*?)(\s*#.*)?$") for req in remove_pins}
        self.removed = {}
        with open(os.path.join(recipe_dir, "meta.yaml")) as f:
            raw = f.read()
        lines = raw.splitlines()
        n = False
        for i, line in enumerate(lines):
            for k, p in remove_pats.items():
                m = p.match(line)
                if m is not None:
                    lines[i] = lines[i].replace(m.group(1), "")
                    removed_version = m.group(1).strip()
                    if not n:
                        n = bool(removed_version)
                    if removed_version:
                        self.removed[k] = removed_version
        if not n:
            return False
        upd = "\n".join(lines) + "\n"
        with open(os.path.join(recipe_dir, "meta.yaml"), "w") as f:
            f.write(upd)
        Rebuild.bump_build_number(os.path.join(recipe_dir, "meta.yaml"))
        return self.migrator_uid(attrs)

    def pr_body(self):
        body = super().pr_body()
        body = body.format(
                    'I noticed that this recipe has version pinnings that may not be needed.\n'
                    'I have removed the following pinnings:\n'
                    '{}\n'
                    'Notes and instructions for merging this PR:\n'
                    '1. Make sure that the removed pinnings are not needed. \n'
                    '2. Please merge the PR only after the tests have passed. \n'
                    "3. Feel free to push to the bot's branch to update this PR if "
                    "needed. \n".format(
                        '\n'.join(['{}: {}'.format(n, p) for n, p in self.removed.items()])
                    ))
        return body

    def commit_message(self):
        return "remove version pinnings"

    def pr_title(self):
        return 'Suggestion: remove version pinnings'

    def pr_head(self):
        return $USERNAME + ':' + self.remote_branch()

    def remote_branch(self):
        return 'pinning'
