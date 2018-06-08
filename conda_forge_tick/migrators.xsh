"""Classes for migrating repos"""
import re
import urllib.error

from conda.models.version import VersionOrder

from rever.tools import (eval_version, indir, hash_url, replace_in_file)

from conda_forge_tick.utils import render_meta_yaml


class Migrator:
    """Base class for Migrators"""
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
        return bool(attrs.get('archived', False))

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
        bool:
            If True continue with PR, if False scrap local folder
        """
        return True

    def pr_body(self):
        """Create a PR message body

        Returns
        -------
        body: str
            The body of the PR message
        """
        body = (
            'This PR was created by the [cf-regro-autotick-bot](https://github.com/regro/cf-scripts).\n\n'
            'The **cf-regro-autotick-bot** is a service to automatically '
            'track the dependency graph, migrate packages, and '
            'propose package version updates for conda-forge. '
            'It is very '
            'likely that the current package version for this feedstock is '
            'out of date or needed migration.\n\n'
            '{}'
            "If you would like a local version of this bot, you might consider using "
            "[rever](https://regro.github.io/rever-docs/). "
            "Rever is a tool for automating software releases and forms the "
            "backbone of the bot's conda-forge PRing capability. Rever is both "
            "conda (`conda install -c conda-forge rever`) and pip "
            "(`pip install re-ver`) installable.\n\n"
            'Finally, feel free to drop us a line if there are any '
            '[issues](https://github.com/regro/cf-scripts/issues)! ')
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


class Version(Migrator):
    """Migrator for version bumping of packages"""
    patterns = (
        # filename, pattern, new
        # set the version
        ('meta.yaml', '  version:\s*[A-Za-z0-9._-]+', '  version: "$VERSION"'),
        ('meta.yaml', '{% set version = ".*" %}',
         '{% set version = "$VERSION" %}'),
        ('meta.yaml', "{% set version = '.*' %}",
         '{% set version = "$VERSION" %}'),
        ('meta.yaml', '{% set version = .* %}',
         '{% set version = "$VERSION" %}'),
        ('meta.yaml', '{%set version = ".*" %}',
         '{%set version = "$VERSION" %}'),
        # reset the build number to 0
        ('meta.yaml', '  number:\s*[0-9]+', '  number: 0'),
        ('meta.yaml', '{%\s*set build_number\s*=\s*"?[0-9]+"?\s*%}',
         '{% set build_number = 0 %}'),
        ('meta.yaml', '{%\s*set build\s*=\s*"?[0-9]+"?\s*%}',
         '{% set build = 0 %}'),
    )

    url_pat = re.compile('  url:\s*([^\s#]+?)\s*(?:(#.*)?\[([^\[\]]+)\])?(?(2)[^\(\)]*)$')
    r_url_pat = re.compile('  url:\s*(?:(#.*)?\[([^\[\]]+)\])?(?(1)[^\(\)]*?)\n(    -.*\n?)*')
    r_urls = re.compile('    -(.+?)(?:#.*)?$', flags=re.M)

    def find_urls(self, text):
        """Get the URLs and platforms in a meta.yaml."""
        urls = []
        lines = text.splitlines()
        for line in lines:
            m = self.url_pat.match(line)
            if m is not None:
                urls.append((m.group(1), m.group(3)))
        matches = self.r_url_pat.finditer(text)
        for m in matches:
            if m is not None:
                r = self.r_urls.findall(m.group())
                urls.append((r, m.group(2)))
        return urls

    def get_hash_patterns(self, filename, urls, hash_type):
        """Get the patterns to replace hash for each platform."""
        pats = ()
        checksum_names = ['hash_value', 'hash', 'hash_val', 'sha256sum',
                          'checksum', hash_type]
        for url, platform in urls:
            if isinstance(url, list):
                for u in url:
                    try:
                        hash = hash_url(u, hash_type)
                        break
                    except urllib.error.HTTPError:
                        continue
            else:
                hash = hash_url(url, hash_type)
            p = '  {}:\s*[0-9A-Fa-f]+'.format(hash_type)
            n = '  {}: {}'.format(hash_type, hash)
            if platform is not None:
                p += '\s*(#.*)\[{}\](?(1)[^\(\)]*)$'.format(platform)
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
        conditional = super().filter(attrs)
        return bool(conditional  # if archived
                or not attrs.get('new_version')  # if no new version
                # if new version is less than current version
                or VersionOrder(str(attrs['new_version'])) <= VersionOrder(str(attrs['version']))
                # if PRed version is greater than newest version
                or VersionOrder(attrs.get('PRed', '0.0.0')) >= VersionOrder(attrs['new_version']))

    def migrate(self, recipe_dir, attrs, hash_type='sha256'):
        # Render with new version but nothing else
        version = attrs['new_version']
        with indir(recipe_dir):
            with open('meta.yaml', 'r') as f:
                text = f.read()
        url = re.search('  url:.*?\n(    -.*\n?)*', text).group()
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
        return True

    def pr_body(self):
        pred = [(name, $SUBGRAPH.node[name]['new_version'])
                for name in list($SUBGRAPH.predecessors($NODE))]
        body = super().pr_body()
        body = body.format('Notes and instructions for merging this PR:\n'
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
        return "updated v" + $VERSION

    def pr_title(self):
        return $PROJECT + ' v' + $VERSION

    def pr_head(self):
        return $USERNAME + ':' + self.remote_branch()

    def remote_branch(self):
        return $VERSION

class JS(Migrator):
    """Migrator for JavaScript syntax"""
    patterns = [
        ('meta.yaml', '  script: npm install -g \.',
         '  script: |\n'
         '    tgz=$(npm pack)\n'
         '    npm install -g $tgz'),
        ('meta.yaml', '   script: |\n', '  script: |')
    ]

    def filter(self, attrs):
        conditional = super().filter(attrs)
        return bool(conditional or
               (attrs.get('meta_yaml', {})
                .get('build', {})
                .get('noarch') != 'generic')
                or (attrs.get('meta_yaml', {})
                    .get('build', {})
                    .get('script') != 'npm install -g .'))

    def migrate(self, recipe_dir, attrs, **kwargs):
        with indir(recipe_dir):
            for f, p, n in self.patterns:
                p = eval_version(p)
                n = eval_version(n)
                replace_in_file(p, n, f,
                                leading_whitespace=False
                                )
        return True

    def pr_body(self):
        body = super().pr_body()
        body.format('Notes and instructions for merging this PR:\n'
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
