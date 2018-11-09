"""Classes for migrating repos"""
import os
import urllib.error

import re
from frozendict import frozendict
from itertools import chain

import networkx as nx
from conda.models.version import VersionOrder
from rever.tools import (eval_version, hash_url, replace_in_file)
from xonsh.lib.os import indir
from conda_smithy.update_cb3 import update_cb3
from conda_smithy.configure_feedstock import get_cfp_file_path
from ruamel.yaml import safe_load, safe_dump

from conda_forge_tick.path_lengths import cyclic_topological_sort
from .utils import render_meta_yaml, UniversalSet

# frozendict serializes its own hash, If this is done then deserialized frozendicts can
# have invalid hashes
def fzd_getstate(self):
    state = self.__dict__.copy()
    state['_hash'] = None
    return state

frozendict.__getstate__ = fzd_getstate


class Migrator:
    """Base class for Migrators"""
    rerender = False

    migrator_version = 0

    build_patterns = ((re.compile('(\s*?)number:\s*([0-9]+)'),
                       'number: {}'),
                      (re.compile('(\s*?){%\s*set build_number\s*=\s*"?([0-9]+)"?\s*%}'),
                       '{{% set build_number = {} %}}'),
                      (re.compile('(\s*?){%\s*set build\s*=\s*"?([0-9]+)"?\s*%}'),
                       '{{% set build = {} %}}')
                     )

    def __init__(self, pr_limit=0):
        self.pr_limit = pr_limit

    def filter(self, attrs: dict) -> bool:
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
            'If this PR was opened in error or needs to be updated please add '
            'the `bot-rerun` label to this PR. The bot will close this PR and '
            'schedule another one.\n\n'
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

    def migrator_uid(self, attrs: dict) -> frozendict:
        """Make a unique id for this migrator and node attrs

        Parameters
        ----------
        attrs: dict
            Node attrs

        Returns
        -------
        nt: frozendict
            The unique id as a frozendict (so it can be used as keys in dicts)
        """
        return frozendict(
            {'migrator_name': self.__class__.__name__,
             'migrator_version': self.migrator_version})

    def order(self, graph, total_graph):
        """Order to run migrations in

        Parameters
        ----------
        graph : nx.DiGraph
            The graph of migratable PRs

        Returns
        -------

        """
        top_level = set(
            node for node in graph if not list(graph.predecessors(node)))
        return cyclic_topological_sort(graph, top_level)

    @classmethod
    def set_build_number(cls, filename):
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
                    old_build_number = int(m.group(2))
                    new_build_number = cls.new_build_number(old_build_number)
                    lines[i] = m.group(1) + n.format(new_build_number)
            upd = '\n'.join(lines) + '\n'
            with open(filename, 'w') as f:
                f.write(upd)

    @classmethod
    def new_build_number(cls, old_number: int):
        """Determine the new build number to use.

        Parameters
        ----------
        old_number : int
            Old build number detected

        Returns
        -------
        new_build_number
        """
        increment = getattr(cls, "bump_number", 1)
        return old_number + increment


class Version(Migrator):
    """Migrator for version bumping of packages"""
    patterns = (
        # filename, pattern, new
        # set the version
        ('meta.yaml', 'version:\s*[A-Za-z0-9._-]+', 'version: "$VERSION"'),
        ('meta.yaml', '{%\s*set\s+version\s*=\s*[^\s]*\s*%}',
            '{% set version = "$VERSION" %}'),
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
            or len([k for k, v in attrs.get('PRed_json', {}).items() if
                    k.get('migrator_name') == 'Version' and
                    v.get('state') == 'open']) > 3
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
            self.set_build_number('meta.yaml')
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
        n = n.copy(version=attrs["new_version"])
        return n

    def _extract_version_from_hash(self, h):
        return h.get('version', '0.0.0')

    @classmethod
    def new_build_number(cls, old_build_number: int):
        if old_build_number >= 1000:
            return 1000
        else:
            return 0


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
            self.set_build_number('meta.yaml')
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

    compilers = {'toolchain', 'toolchain3', 'gcc', 'cython', 'pkg-config',
                 'autotools', 'make', 'cmake', 'autconf', 'libtool', 'm4',
                 'ninja', 'jom', 'libgcc', 'libgfortran'}

    def __init__(self, pr_limit=0):
        super().__init__(pr_limit)
        self.cfp = get_cfp_file_path()[0]

    def filter(self, attrs):
        for req in attrs.get('req', []):
            if req.endswith('_compiler_stub'):
                return True
        conditional = super().filter(attrs)
        return (conditional or not any(x in attrs.get('req', []) for x in self.compilers))

    def migrate(self, recipe_dir, attrs, **kwargs):
        with indir(recipe_dir):
            content, self.messages = update_cb3('meta.yaml', self.cfp)
            with open('meta.yaml', 'w') as f:
                f.write(content)
            self.set_build_number('meta.yaml')
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
                    .format(self.messages))
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
    unallowed_reqs = ['toolchain', 'toolchain3', 'gcc', 'cython', 'clangdev']
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
            self.set_build_number('meta.yaml')
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
    bump_number = 1

    def __init__(self, graph=None, name=None, pr_limit=0, top_level=None,
                 cycles=None):
        super().__init__(pr_limit)
        if graph == None:
            self.graph = nx.DiGraph()
        else:
            self.graph = graph
        self.name = name
        self.top_level = top_level
        self.cycles = set(chain.from_iterable(cycles))

    def filter(self, attrs):
        if super().filter(attrs):
            return True
        if attrs['feedstock_name'] not in self.graph:
            return True
        # If in top level or in a cycle don't check for upstreams just build
        if ((self.top_level and attrs['feedstock_name'] in self.top_level)
            or (self.cycles and attrs['feedstock_name'] in self.cycles)):
            return False
        # Check if all upstreams have been built
        for node in self.graph.predecessors(attrs['feedstock_name']):
            att = self.graph.node[node]
            muid = self.migrator_uid(att)
            if muid not in att.get('PRed', []):
                return True
            # This is due to some PRed_json loss due to bad graph deploy outage
            m_pred_jsons = att.get('PRed_json').get(muid)
            if m_pred_jsons and m_pred_jsons.get('state', '') == 'open':
                return True
        return False

    def migrate(self, recipe_dir, attrs, **kwargs):
        with indir(recipe_dir):
            self.set_build_number('meta.yaml')
        return self.migrator_uid(attrs)

    def pr_body(self):
        body = super().pr_body()
        body = body.format(
                    'It is likely this feedstock needs to be rebuilt.\n'
                    'Notes and instructions for merging this PR:\n'
                    '1. Please merge the PR only after the tests have passed. \n'
                    "2. Feel free to push to the bot's branch to update this PR if needed. \n"
                    "{}\n"
                    )
        return body

    def commit_message(self):
        return "bump build number"

    def pr_title(self):
        if self.name:
            return 'Rebuild for ' + self.name
        else:
            return 'Bump build number'

    def pr_head(self):
        return $USERNAME + ':' + self.remote_branch()

    def remote_branch(self):
        return 'rebuild'

    def migrator_uid(self, attrs):
        n = super().migrator_uid(attrs)
        n = n.copy(name=self.name)
        return n

    def order(self, graph, total_graph):
        """Run the order by number of decendents, ties are resolved by package name"""
        return sorted(graph, key=lambda x: (len(nx.descendants(total_graph, x)), x),
                      reverse=True)


class CompilerRebuild(Rebuild):
    bump_number = 1000
    migrator_version = 1

    def migrate(self, recipe_dir, attrs, **kwargs):
        with indir(recipe_dir + '/..'):
            with open('conda-forge.yml', 'r') as f:
                y = safe_load(f)
            y.update({'compiler_stack': 'comp7',
                      'max_py_ver': '37',
                      'max_r_ver': '35'})
            with open('conda-forge.yml', 'w') as f:
                safe_dump(y, f)
        return super().migrate(recipe_dir, attrs, **kwargs)

    def pr_body(self):
        body = super().pr_body()
        body = body.format(
                    "\n"
                    "**Please note that if you close this PR we presume that "
                    "the feedstock has been rebuilt, so if you are going to "
                    "perform the rebuild yourself don't close this PR until "
                    "the your rebuild has been merged.**\n\n"
                    "This package has the following downstream children:\n"
                    "{}\n"
                    "And potentially more.".format('\n'.join(
                        [a[1] for a in list(
                            self.graph.out_edges($PROJECT))[:5]])))
        return body


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
        self.set_build_number(os.path.join(recipe_dir, "meta.yaml"))
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


class LibjpegTurbo(Migrator):
    """Migrator for swapping jpeg 9 with libjpeg-turbo."""
    migrator_version = 0
    rerender = True
