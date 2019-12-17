"""Classes for migrating repos"""
import os
import urllib.error

import re
from itertools import chain
from textwrap import dedent
import warnings
from itertools import permutations

import networkx as nx
import conda.exceptions
from conda.models.version import VersionOrder
from rever.tools import (eval_version, hash_url, replace_in_file)
from xonsh.lib.os import indir
from conda_smithy.update_cb3 import update_cb3
from conda_smithy.configure_feedstock import get_cfp_file_path

from conda_build.source import provide
from conda_build.config import Config
from conda_build.api import render

from ruamel.yaml import safe_load, safe_dump

import requests

from conda_forge_tick.path_lengths import cyclic_topological_sort
from .utils import render_meta_yaml, UniversalSet, frozen_to_json_friendly, \
    as_iterable, parse_meta_yaml, CB_CONFIG


try:
    from conda_smithy.lint_recipe import NEEDED_FAMILIES
except ImportError:
    NEEDED_FAMILIES = ["gpl", "bsd", "mit", "apache", "psf"]


def _no_pr_pred(pred):
    l = []
    for pr in pred:
        l.append({'data': pr['data'], 'keys': pr['keys']})
    return l

class MiniMigrator:
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
        return True

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
        return


class PipMigrator(MiniMigrator):
    bad_install = ('python setup.py install', 'python -m pip install --no-deps --ignore-installed .')
    def filter(self, attrs: dict) -> bool:
        scripts = as_iterable(attrs.get('meta_yaml', {}).get('build', {}).get('script', []))
        return not bool(set(self.bad_install) & set(scripts))

    def migrate(self, recipe_dir, attrs, **kwargs):
        with indir(recipe_dir):
            for b in self.bad_install:
                replace_in_file(f'script: {b}', "script: {{ PYTHON }} -m pip install . --no-deps -vv", 'meta.yaml')


class LicenseMigrator(MiniMigrator):
    def filter(self, attrs: dict) -> bool:
        license = attrs.get('meta_yaml', {}).get('about', {}).get('license', '')
        license_fam = (attrs.get('meta_yaml', {}).get('about', {}).get('license_family', '').lower() or
                       license.lower().partition('-')[0].partition('v')[0])
        if license_fam in NEEDED_FAMILIES and 'license_file' not in attrs.get('meta_yaml', {}).get('about', {}):
            return False
        return True

    def migrate(self, recipe_dir, attrs, **kwargs):
        # Use conda build to do all the downloading/extracting bits
        md = render(recipe_dir, config=Config(**CB_CONFIG))
        if not md:
            return
        md = md[0][0]
        # go into source dir
        cb_work_dir = provide(md)
        with indir(cb_work_dir):
            # look for a license file
            license_files = [(s for s in os.listdir('.') if any(s.lower().startswith(k) for k in ['license', 'copying', 'copyright']))]
            # if there is a license file in tarball update things
        rm -r @(cb_work_dir)
        if license_files:
            with indir(recipe_dir):
                '''BSD 3-Clause License
                  Copyright (c) 2017, Anthony Scopatz
                  Copyright (c) 2018, The Regro Developers
                  All rights reserved.'''
                with open('meta.yaml', 'r') as f:
                    raw = f.read()
                lines = raw.splitlines()
                ptn = re.compile(r'(\s*?)' + 'license:')
                for i, line in enumerate(lines):
                   m = ptn.match(line)
                   if m is not None:
                       break
                ws = m.group(1)
                if len(license_files) == 1:
                    replace_in_file(line, line + "\n" + ws + f"license_file: {next(iter(license_files))}", 'meta.yaml')
                else:
                    # note that this white space is not perfect but works for most of the situations
                    replace_in_file(line, line + "\n" + ws + "license_file: \n" + ''.join(f"{ws*2}- {z} \n" for z in license_files), 'meta.yaml')

        # if license not in tarball do something!
        # check if

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

    def __init__(self, pr_limit=0, obj_version=None, piggy_back_migrations=None):
        if piggy_back_migrations is None:
            piggy_back_migrations = []
        self.piggy_back_migrations = piggy_back_migrations
        self.pr_limit = pr_limit
        self.obj_version=obj_version


    def filter(self, attrs: dict, not_bad_str_start='') -> bool:
        """ If true don't act upon node

        Parameters
        ----------
        attrs : dict
            The node attributes
        not_bad_str_start : str, optional
            If the 'bad' notice starts with the string then it is not
            to be excluded. For example, rebuild migrations don't need
            to worry about if the upstream can be fetched. Defaults to ``''``

        Returns
        -------
        bool :
            True if node is to be skipped
        """
        # never run on archived feedstocks
        # don't run on things we've already done
        # don't run on bad nodes
        return (attrs.get('archived', False)
                or frozen_to_json_friendly(self.migrator_uid(attrs)
                                           )['data'] in (z['data'] for z in attrs.get('PRed', []))
                or (attrs.get('bad', False)
                    # This could be a dict, but then we can't fix it
                    and isinstance(attrs.get('bad'), str)
                    # TODO: support a list of stings?
                    and not attrs.get('bad').startswith(not_bad_str_start)))

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
        for mini_migrator in self.piggy_back_migrations:
            if not mini_migrator.filter(attrs):
                mini_migrator.migrate(recipe_dir, attrs, **kwargs)
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
            '[issues](https://github.com/regro/cf-scripts/issues)!\n'+
            f'This PR was generated by {$CIRCLE_BUILD_URL}, please use this URL for debugging'+
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

    def migrator_uid(self, attrs: dict) -> frozen_to_json_friendly:
        """Make a unique id for this migrator and node attrs

        Parameters
        ----------
        attrs: dict
            Node attrs

        Returns
        -------
        nt: frozen_to_json_friendly
            The unique id as a frozen_to_json_friendly (so it can be used as keys in dicts)
        """
        d = {'migrator_name': self.__class__.__name__,
             'migrator_version': self.migrator_version,
             'bot_rerun': False
             }
        # Carveout for old migrators w/o obj_versions
        if self.obj_version:
            d.update(migrator_object_version=self.obj_version)
        return d

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
            node for node in graph if not list(graph.predecessors(node)) or list(graph.predecessors(node)) == [node])
        return cyclic_topological_sort(graph, top_level)

    def set_build_number(self, filename):
        """Bump the build number of the specified recipe.

        Parameters
        ----------
        filename : str
            Path the the meta.yaml

        """

        for p, n in self.build_patterns:
            with open(filename, 'r') as f:
                raw = f.read()
            lines = raw.splitlines()
            for i, line in enumerate(lines):
                m = p.match(line)
                if m is not None:
                    old_build_number = int(m.group(2))
                    new_build_number = self.new_build_number(old_build_number)
                    lines[i] = m.group(1) + n.format(new_build_number)
            upd = '\n'.join(lines) + '\n'
            with open(filename, 'w') as f:
                f.write(upd)

    def new_build_number(self, old_number: int):
        """Determine the new build number to use.

        Parameters
        ----------
        old_number : int
            Old build number detected

        Returns
        -------
        new_build_number
        """
        increment = getattr(self, "bump_number", 1)
        return old_number + increment

    @classmethod
    def migrator_label(cls):
        # This is the label that the bot will attach to a pr made by the bot
        return {
            'name': f'bot-{cls.__name__.lower()}',
            'description': cls.__doc__.strip(),
            'color': '#6c64ff',
        }


class Version(Migrator):
    """Migrator for version bumping of packages"""
    max_num_prs = 3
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
        result = bool(
            conditional  # if archived/finished
            or len([k for k in attrs.get('PRed', []) if
                    k['data'].get('migrator_name') == 'Version' and
                    k.get('PR', {}).get('state', None) == 'open']) > self.max_num_prs
            or not attrs.get('new_version')  # if no new version
        )
        try:
            version_filter = (
                # if new version is less than current version
                (VersionOrder(str(attrs['new_version'])) <=
                    VersionOrder(str(attrs.get('version', '0.0.0'))))
                # if PRed version is greater than newest version
                or any(VersionOrder(self._extract_version_from_hash(h)) >=
                    VersionOrder(str(attrs['new_version'])
                                    ) for h in attrs.get('PRed', set()))
                )
        except conda.exceptions.InvalidVersionSpec as e:
            warnings.warn(f"Failed to filter to to invalid version for {attrs}\nException: {e}")
            version_filter = True
        return result or version_filter

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

        # render the text and check that the URL exists, if it doesn't try variations
        # if variations then update url
        rendered = parse_meta_yaml(render_meta_yaml(text))
        # only run for single url recipes as the moment
        if isinstance(rendered['source'], dict) and isinstance(rendered['source'].get('url', []), str) and requests.get(rendered['source']['url']).status_code != 200:
            with indir(recipe_dir):
                for a, b in permutations(['.zip', '.tar.gz']):
                    text = text.replace(a, b)
                    rendered = parse_meta_yaml(render_meta_yaml(text))
                    if requests.get(rendered['source']['url']).status_code == 200:
                        with open('meta.yaml', 'w') as f:
                            f.write(text)
                        break
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
        return super().migrate(recipe_dir, attrs)

    def pr_body(self):
        pred = [(name, $SUBGRAPH.nodes[name]['payload']['new_version'])
                for name in list($SUBGRAPH.predecessors($NODE))]
        body = super().pr_body()
        body = body.format(
            'It is very likely that the current package version for this '
            'feedstock is out of date.\n'
            'Notes for merging this PR:\n'
            "1. Feel free to push to the bot's branch to update this PR if needed.\n"
            "2. The bot will almost always only open one PR per version.\n"
            "Checklist before merging this PR:\n"
            "- [ ] Dependencies have been updated if changed\n"
            "- [ ] Tests have passed \n"
            "- [ ] Updated license if changed and `license_file` is packaged \n"
            "\n"
            "Note that the bot will stop issuing PRs if more than {} Version bump PRs "
            "generated by the bot are open. If you don't want to package a particular "
            "version please close the PR\n"
            "\n".format(self.max_num_prs)
            )
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
        n.update(version=attrs["new_version"])
        return n

    def _extract_version_from_hash(self, h):
        return h.get('version', '0.0.0')

    @classmethod
    def new_build_number(cls, old_build_number: int):
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
        return super().migrate(recipe_dir, attrs)

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
        return super().migrate(recipe_dir, attrs)

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
        return super().migrate(recipe_dir, attrs)

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


class NoarchR(Noarch):
    migrator_version = 0
    rerender = True
    bump_number = 1

    def filter(self, attrs):
        conditional = (Migrator.filter(self, attrs) or
                       attrs.get('meta_yaml', {}).get('outputs') or
                       attrs.get('meta_yaml', {}).get('build', {}).get('noarch')
                      )
        if conditional:
            return True
        r = False
        for req in attrs.get('req', []):
            if self.compiler_pat.match(req) or req in self.unallowed_reqs:
                return True

        if attrs['feedstock_name'].startswith("r-"):
            r = True
        if not r:
            return True

        ## R recipes tend to have some things in their build / test that have selectors

        # for line in attrs.get('raw_meta_yaml', '').splitlines():
        #    if self.sel_pat.match(line):
        #        return True
        return False

    def migrate(self, recipe_dir, attrs, **kwargs):
        check_for = ['toolchain', 'libgcc', 'compiler']

        noarch = not any(c in attrs['raw_meta_yaml'] for c in check_for)

        r_pkg_name = attrs['feedstock_name'][2:]
        r_noarch_build_sh = dedent("""
        #!/bin/bash
        if [[ $target_platform =~ linux.* ]] || [[ $target_platform == win-32 ]] || [[ $target_platform == win-64 ]] || [[ $target_platform == osx-64 ]]; then
          export DISABLE_AUTOBREW=1
          mv DESCRIPTION DESCRIPTION.old
          grep -v '^Priority: ' DESCRIPTION.old > DESCRIPTION
          $R CMD INSTALL --build .
        else
          mkdir -p $PREFIX/lib/R/library/{r_pkg_name}
          mv * $PREFIX/lib/R/library/{r_pkg_name}
        fi
        """).format(r_pkg_name=r_pkg_name)

        with indir(recipe_dir):
            if noarch:
                with open('build.sh', 'w') as f:
                    f.writelines(r_noarch_build_sh)
            new_text = ''
            with open('meta.yaml', 'r') as f:
                lines = f.readlines()
                lines_stripped = [line.rstrip() for line in lines]
                if noarch and 'build:' in lines_stripped:
                    index = lines_stripped.index('build:')
                    spacing = 2
                    s = len(lines[index+1].lstrip()) - len(lines[index+1])
                    if s > 0:
                        spacing = s
                    lines[index] = lines[index] + " "*spacing + "noarch: generic\n"
                regex_unix1 = re.compile('license_file: \'{{ environ\["PREFIX"\] }}/lib/R/share/licenses/(\S+)\'\s+# \[unix\]')
                regex_unix2 = re.compile('license_file: \'{{ environ\["PREFIX"\] }}\\\/lib\\\/R\\\/share\\\/licenses\\\/(.+)\'\\s+# \[unix\]')
                regex_win = re.compile('license_file: \'{{ environ\["PREFIX"\] }}\\\R\\\share\\\licenses\\\(\S+)\'\s+# \[win\]')
                for i, line in enumerate(lines_stripped):
                    if noarch and line.lower().strip().startswith("skip: true"):
                        lines[i] = ""
                    # Fix path to licenses
                    if regex_unix1.match(line.strip()):
                        lines[i] = regex_unix1.sub('license_file: \'{{ environ["PREFIX"] }}/lib/R/share/licenses/\\1\'',
                                                   lines[i])
                    if regex_unix2.match(line.strip()):
                        lines[i] = regex_unix2.sub('license_file: \'{{ environ["PREFIX"] }}/lib/R/share/licenses/\\1\'',
                                                   lines[i])
                    if regex_win.match(line.strip()):
                        lines[i] = ''

                new_text = ''.join(lines)
            if new_text:
                with open('meta.yaml', 'w') as f:
                    f.writelines(new_text)
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
        return "add noarch r"

    def pr_title(self):
        if self.name:
            return 'Noarch R for ' + self.name
        else:
            return 'Bump build number'

    def remote_branch(self):
        return 'r-noarch'


class Rebuild(Migrator):
    """Migrator for bumping the build number."""
    migrator_version = 0
    rerender = True
    bump_number = 1
    # TODO: add a description kwarg for the status page at some point.
    def __init__(self, graph=None, name=None, pr_limit=0, top_level=None,
                 cycles=None, obj_version=None):
        super().__init__(pr_limit, obj_version)
        if graph == None:
            self.graph = nx.DiGraph()
        else:
            self.graph = graph
        self.name = name
        self.top_level = top_level
        self.cycles = set(chain.from_iterable(cycles or []))

    def filter(self, attrs):
        if super().filter(attrs, 'Upstream:'):
            return True
        if attrs['feedstock_name'] not in self.graph:
            return True
        # If in top level or in a cycle don't check for upstreams just build
        if ((self.top_level and attrs['feedstock_name'] in self.top_level)
            or (self.cycles and attrs['feedstock_name'] in self.cycles)):
            return False
        # Check if all upstreams have been built
        for node in self.graph.predecessors(attrs['feedstock_name']):
            att = self.graph.nodes[node]['payload']
            muid = frozen_to_json_friendly(self.migrator_uid(att))
            if muid not in _no_pr_pred(att.get('PRed', [])) and not att.get('archived', False):
                return True
            # This is due to some PRed_json loss due to bad graph deploy outage
            for m_pred_json in att.get('PRed', []):
                if m_pred_json['data'] == muid['data']:
                    break
            else:
                m_pred_json = None
            # note that if the bot is missing the PR we assume it is open
            # so that errors halt the migration and can be fixed
            if m_pred_json and m_pred_json.get('PR', {'state': 'open'}).get('state', '') == 'open':
                return True
        return False

    def migrate(self, recipe_dir, attrs, **kwargs):
        with indir(recipe_dir):
            self.set_build_number('meta.yaml')
        return super().migrate(recipe_dir, attrs)

    def pr_body(self):
        body = super().pr_body()
        additional_body = ("This PR has been triggered in an effort to update **{0}**.\n\n"
                           "Notes and instructions for merging this PR:\n"
                           "1. Please merge the PR only after the tests have passed. \n"
                           "2. Feel free to push to the bot's branch to update this PR if needed. \n"
                           "**Please note that if you close this PR we presume that "
                           "the feedstock has been rebuilt, so if you are going to "
                           "perform the rebuild yourself don't close this PR until "
                           "the your rebuild has been merged.**\n\n"
                           "This package has the following downstream children:\n"
                           "{1}\n"
                           "And potentially more."
                           "".format(self.name,
                                     '\n'.join([a[1] for a in list(self.graph.out_edges($PROJECT))[: 5]])))
        body = body.format(additional_body)
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
        s_obj = str(self.obj_version) if self.obj_version else ''
        return 'rebuild' + self.name.lower().replace(' ', '_') + str(self.migrator_version) + s_obj

    def migrator_uid(self, attrs):
        n = super().migrator_uid(attrs)
        n.update(name=self.name)
        return n

    def order(self, graph, total_graph):
        """Run the order by number of decendents, ties are resolved by package name"""
        return sorted(graph, key=lambda x: (len(nx.descendants(total_graph, x)), x),
                      reverse=True)


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
        return super().migrate(recipe_dir, attrs)

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


class Replacement(Migrator):
    """Migrator for replacing one package with another.

    Parameters
    ----------
    old_pkg : str
        The package to be replaced.
    new_pkg : str
        The package to replace the `old_pkg`.
    rationale : str
        The reason the for the migration. Should be a full statement.
    """
    migrator_version = 0
    rerender = True

    def __init__(self, *, old_pkg, new_pkg, rationale, pr_limit=0):
        super().__init__(pr_limit)
        self.old_pkg = old_pkg
        self.new_pkg = new_pkg
        self.pattern = re.compile("\s*-\s*(%s)(\s+|$)" % old_pkg)
        self.packages = set([old_pkg])
        self.rationale = rationale

    def filter(self, attrs):
        return (super().filter(attrs) or
                len(attrs.get("req", set()) & self.packages) == 0)

    def migrate(self, recipe_dir, attrs, **kwargs):
        with open(os.path.join(recipe_dir, "meta.yaml")) as f:
            raw = f.read()
        lines = raw.splitlines()
        n = False
        for i, line in enumerate(lines):
            m = self.pattern.match(line)
            if m is not None:
                lines[i] = lines[i].replace(m.group(1), self.new_pkg)
                n = True
        if not n:
            return False
        upd = "\n".join(lines) + "\n"
        with open(os.path.join(recipe_dir, "meta.yaml"), "w") as f:
            f.write(upd)
        self.set_build_number(os.path.join(recipe_dir, "meta.yaml"))
        return super().migrate(recipe_dir, attrs)

    def pr_body(self):
        body = super().pr_body()
        body = body.format(
                    'I noticed that this recipe depends on `%s` instead of \n'
                    '`%s`. %s \n'
                    'This PR makes this change.'
                    '\n'
                    'Notes and instructions for merging this PR:\n'
                    '1. Make sure that the recipe can indeed only depend on `%s`. \n'
                    '2. Please merge the PR only after the tests have passed. \n'
                    "3. Feel free to push to the bot's branch to update this PR if "
                    "needed. \n" % (
                        self.old_pkg, self.new_pkg, self.rationale,
                        self.new_pkg))
        return body

    def commit_message(self):
        return "use %s instead of %s" % (self.new_pkg, self.old_pkg)

    def pr_title(self):
        return 'Suggestion: depend on %s instead of %s' % (
            self.new_pkg, self.old_pkg)

    def pr_head(self):
        return $USERNAME + ':' + self.remote_branch()

    def remote_branch(self):
        return '%s-to-%s-migration' % (self.old_pkg, self.new_pkg)


class ArchRebuild(Rebuild):
    """
    A Migrator that add aarch64 and ppc64le builds to feedstocks
    """
    migrator_version = 1
    rerender = True
    # We purposefully don't want to bump build number for this migrator
    bump_number = 0
    # We are constraining the scope of this migrator
    with indir('../conda-forge-pinning-feedstock/recipe/migrations'), open('arch_rebuild.txt', 'r') as f:
        target_packages = set(f.read().split())
    ignored_packages = {'make', 'perl', 'toolchain', 'posix',
        'patchelf', # weird issue
    }
    arches = {
        "linux_aarch64": "default",
        "linux_ppc64le": "default",
    }

    def __init__(self, graph=None, name=None, pr_limit=0, top_level=None,
                 cycles=None):
        super().__init__(graph=graph, name=name, pr_limit=pr_limit, top_level=top_level,
                         cycles=cycles)
        # filter the graph down to the target packages
        if self.target_packages:
            packages = self.target_packages.copy()
            for target in self.target_packages:
                if target in self.graph.nodes:
                    packages.update(nx.ancestors(self.graph, target))
            self.graph.remove_nodes_from([n for n in self.graph if n not in packages])
        # filter out stub packages and ignored packages
        for node in list(self.graph.nodes):
            if (node.endswith('_stub')
                    or (node.startswith('m2-'))
                    or (node.startswith('m2w64-'))
                    or (node in self.ignored_packages)):
                self.graph.remove_node(node)

    def filter(self, attrs):
        if super().filter(attrs):
            return True
        muid = frozen_to_json_friendly(self.migrator_uid(attrs))
        for arch in self.arches:
            configured_arch = attrs.get("conda-forge.yml", {}).get("provider", {}).get(arch)
            if configured_arch:
                return muid in _no_pr_pred(attrs.get('PRed', []))

    def migrate(self, recipe_dir, attrs, **kwargs):
        with indir(recipe_dir + '/..'):
            with open('conda-forge.yml', 'r') as f:
                y = safe_load(f)
            if 'provider' not in y:
                y['provider'] = {}
            for k, v in self.arches.items():
                if k not in y['provider']:
                    y['provider'][k] = v

            with open('conda-forge.yml', 'w') as f:
                safe_dump(y, f)
        return super().migrate(recipe_dir, attrs, **kwargs)

    def pr_title(self):
        return 'Arch Migrator'

    def pr_body(self):
        body = dedent("""\
        This feedstock is being rebuilt as part of the aarch64/ppc64le migration.

        **Feel free to merge the PR if CI is all green, but please don't close it
        without reaching out the the ARM migrators first at @conda-forge/arm-arch.**
        """)
        return body

    def remote_branch(self):
        return super().remote_branch() + '_arch'


class BlasRebuild(Rebuild):
    """Migrator for rebuilding for blas 2.0."""
    migrator_version = 0
    rerender = True
    bump_number = 1

    blas_patterns = [
        re.compile('(\s*?)-\s*(blas|openblas|mkl|(c?)lapack)'),
        re.compile('(\s*?){%\s*set variant\s*=\s*"openblas"?\s*%}'),
    ]

    def __init__(self, graph=None, name=None, pr_limit=0, top_level=None,
                 cycles=None, obj_version=None):
        super().__init__(graph=graph, name="blas2", pr_limit=pr_limit, top_level=top_level,
                         cycles=cycles, obj_version=obj_version)

    def migrate(self, recipe_dir, attrs, **kwargs):
        with indir(recipe_dir):
            # Update build number
            # Remove blas related packages and features
            with open('meta.yaml', 'r') as f:
                lines = f.readlines()
            reqs_line = "build:"
            for i, line in enumerate(lines):
                if line.strip() == "host:":
                    reqs_line = "host:"
                for blas_pattern in self.blas_patterns:
                    m = blas_pattern.match(line)
                    if m is not None:
                        lines[i] = ""
                        break
            for i, line in enumerate(lines):
                sline = line.lstrip()
                if len(sline) != len(line) and line.strip() == reqs_line:
                    for dep in ["libblas", "libcblas"]:
                        print(lines[i], len(line)-len(sline))
                        lines[i] = lines[i] + " "*(len(line)-len(sline)) + "  - " + dep + "\n"
            new_text = ''.join(lines)
            with open('meta.yaml', 'w') as f:
                f.write(new_text)
        return super().migrate(recipe_dir, attrs)

    def pr_body(self):
        body = super().pr_body()
        additional_body = ("This PR has been triggered in an effort to update for new BLAS scheme.\n\n"
                           "New BLAS scheme builds conda packages against the Reference-LAPACK's libraries\n"
                           "which allows to change the BLAS implementation at install time by the user.\n\n"
                           "Checklist:\n"
                           "1. Tests has passed. \n"
                           "2. Added `liblapack, liblapacke` if they are needed. \n"
                           "3. Removed `libcblas` if `cblas_*` API is not used. \n"
                           "Feel free to push to the bot's branch to update this PR if needed. \n"
                           "**Please note that if you close this PR we presume that "
                           "the feedstock has been rebuilt, so if you are going to "
                           "perform the rebuild yourself don't close this PR until "
                           "the your rebuild has been merged.**\n\n"
                           "This package has the following downstream children:\n"
                           "{0}\n"
                           "And potentially more."
                           "".format('\n'.join([a[1] for a in list(self.graph.out_edges($PROJECT))[: 5]])))
        body = body.format(additional_body)
        return body

    def commit_message(self):
        return "Rebuild for new BLAS scheme"

    def pr_title(self):
        return 'Rebuild for new BLAS scheme'


class RBaseRebuild(Rebuild):
    """Migrator for rebuilding all R packages."""
    migrator_version = 0
    rerender = True
    bump_number = 1

    def migrate(self, recipe_dir, attrs, **kwargs):
        # Set the provider to Azure only
        with indir(recipe_dir + '/..'):
            if os.path.exists('conda-forge.yml'):
                with open('conda-forge.yml', 'r') as f:
                    y = safe_load(f)
            else:
                y = {}
            if 'provider' not in y:
                y['provider'] = {}
            y['provider']['win'] = 'azure'
            with open('conda-forge.yml', 'w') as f:
                safe_dump(y, f)

        with indir(recipe_dir):
            with open('meta.yaml', 'r') as f:
                text = f.read()

            changed = False
            lines = text.split("\n")

            if attrs['feedstock_name'].startswith("r-") and "- conda-forge/r" not in text \
                    and any(a in text for a in ["johanneskoester", "bgruening", "daler", "jdblischak", "cbrueffer", "dbast", "dpryan79"]):
                for i, line in enumerate(lines):
                    if line.strip() == "recipe-maintainers:" and i + 1 < len(lines):
                        lines[i] = line + "\n" + lines[i+1][:lines[i+1].index("-")] + "- conda-forge/r"

                changed = True

            for i, line in enumerate(lines):
                if line.lstrip().startswith("- {{native}}toolchain"):
                    replaced_lines = []
                    for comp in ['c', 'cxx', 'fortran']:
                        if "compiler('"+ comp + "')" in text:
                            replaced_lines.append(line.replace("- {{native}}toolchain", "- {{ compiler('m2w64_"+ comp + "') }}"))
                    if len(replaced_lines) != 0:
                        lines[i] = '\n'.join(replaced_lines)
                        changed = True
                        break

            if changed:
                with open('meta.yaml', 'w') as f:
                    f.write('\n'.join(lines))

        return super().migrate(recipe_dir, attrs)


class GFortranOSXRebuild(Rebuild):
    migrator_version = 0
    rerender = True
    bump_number = 1

    def pr_body(self):
        body = super(Rebuild, self).pr_body()
        additional_body = ("This PR has been triggered in an effort to update **{0}**.\n\n"
                           "Notes and instructions for merging this PR:\n"
                           "1. Please merge the PR only after the tests have passed. \n"
                           "2. Feel free to push to the bot's branch to update this PR if needed. \n"
                           "**Please note that if you close this PR we presume that "
                           "the feedstock has been rebuilt, so if you are going to "
                           "perform the rebuild yourself don't close this PR until "
                           "the your rebuild has been merged.**\n\n"
                           "This package has the following downstream children:\n"
                           "{1}\n"
                           "And potentially more."
                           "".format("to gfortran 7 for OSX",
                                     '\n'.join([a[1] for a in list(self.graph.out_edges($PROJECT))[: 5]])))
        body = body.format(additional_body)
        return body

    def commit_message(self):
        return "Rebuild for gfortran 7 for OSX"

    def pr_title(self):
        return "Rebuild for gfortran 7 for OSX"


# This may replace Rebuild
class MigrationYaml(Migrator):
    """Migrator for bumping the build number."""
    migrator_version = 0
    rerender = True

    # TODO: add a description kwarg for the status page at some point.
    # TODO: make yaml_contents an arg?
    def __init__(self,
                 yaml_contents,
                 graph=None, name=None, pr_limit=50, top_level=None,
                 cycles=None, migration_number=None,
                 bump_number=1,
                 piggy_back_migrations=None, **kwargs):
        super().__init__(pr_limit, migration_number, piggy_back_migrations=piggy_back_migrations)
        self.yaml_contents = yaml_contents
        if graph is None:
            self.graph = nx.DiGraph()
        else:
            self.graph = graph
        self.name = name
        self.top_level = top_level
        self.cycles = set(chain.from_iterable(cycles or []))

        # auto set the pr_limit for initial things
        number_pred = len([k for k, v in self.graph.nodes.items() if self.migrator_uid(v.get('payload', {})) in [vv.get('data', {}) for vv in v.get('payload', {}).get('PRed', [])]])
        if number_pred == 0 :
            self.pr_limit = 2
        elif number_pred < 7:
            self.pr_limit = 5
        self.bump_number = bump_number
        print(self.yaml_contents)


    def filter(self, attrs):
        if super().filter(attrs, 'Upstream:'):
            return True
        if attrs['feedstock_name'] not in self.graph:
            return True
        # If in top level or in a cycle don't check for upstreams just build
        if ((self.top_level and attrs['feedstock_name'] in self.top_level)
            or (self.cycles and attrs['feedstock_name'] in self.cycles)):
            return False
        # Check if all upstreams have been built
        for node in self.graph.predecessors(attrs['feedstock_name']):
            att = self.graph.nodes[node]['payload']
            muid = frozen_to_json_friendly(self.migrator_uid(att))
            if muid not in _no_pr_pred(att.get('PRed', [])) and not att.get('archived', False):
                return True
            # This is due to some PRed_json loss due to bad graph deploy outage
            for m_pred_json in att.get('PRed', []):
                if m_pred_json['data'] == muid['data']:
                    break
            else:
                m_pred_json = None
            if m_pred_json and m_pred_json['PR'].get('state', '') == 'open':
                return True
        return False

    def migrate(self, recipe_dir, attrs, **kwargs):
        # in case the render is old
        os.makedirs(os.path.join(recipe_dir, '../.ci_support'), exist_ok=True)
        with indir(os.path.join(recipe_dir, '../.ci_support')):
            os.makedirs('migrations', exist_ok=True)
            with indir('migrations'):
                with open(f'{self.name}.yaml', 'w') as f:
                    f.write(self.yaml_contents)
                git add .
        with indir(recipe_dir):
            self.set_build_number('meta.yaml')
        return super().migrate(recipe_dir, attrs)

    def pr_body(self):
        body = super().pr_body()
        additional_body = ("This PR has been triggered in an effort to update **{0}**.\n\n"
                           "Notes and instructions for merging this PR:\n"
                           "1. Please merge the PR only after the tests have passed. \n"
                           "2. Feel free to push to the bot's branch to update this PR if needed. \n"
                           "**Please note that if you close this PR we presume that "
                           "the feedstock has been rebuilt, so if you are going to "
                           "perform the rebuild yourself don't close this PR until "
                           "the your rebuild has been merged.**\n\n"
                           "This package has the following downstream children:\n"
                           "{1}\n"
                           "And potentially more."
                           "".format(self.name,
                                     '\n'.join([a[1] for a in list(self.graph.out_edges($PROJECT))[: 5]])))
        body = body.format(additional_body)
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
        s_obj = str(self.obj_version) if self.obj_version else ''
        return 'rebuild-' + self.name.lower().replace(' ', '_') + str(self.migrator_version) + s_obj

    def migrator_uid(self, attrs):
        n = super().migrator_uid(attrs)
        n.update(name=self.name)
        return n

    def order(self, graph, total_graph):
        """Run the order by number of decendents, ties are resolved by package name"""
        return sorted(graph, key=lambda x: (len(nx.descendants(total_graph, x)), x),
                      reverse=True)
