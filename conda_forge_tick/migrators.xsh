"""Classes for migrating repos"""
import urllib.error

from conda.models.version import VersionOrder

from rever.tools import (eval_version, indir, hash_url, replace_in_file)

from conda_forge_tick.utils import parsed_meta_yaml


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
        # set the hash
        ('meta.yaml', '{% set $HASH_TYPE = "[0-9A-Fa-f]+" %}',
         '{% set $HASH_TYPE = "$HASH" %}'),
        ('meta.yaml', '  $HASH_TYPE:\s*[0-9A-Fa-f]+', '  $HASH_TYPE: $HASH'),

    )

    more_patterns = []
    checksum_names = ['hash_value', 'hash', 'hash_val', 'sha256sum',
                      'checksum',
                      '$HASH_TYPE']
    delim = ["'", '"']
    sets = [' set', 'set']
    base1 = '''{{%{set} {checkname} = {d}[0-9A-Fa-f]+{d} %}}'''
    base2 = '''{{%{set} {checkname} = {d}$HASH{d} %}}'''
    for cn in checksum_names:
        for s in sets:
            for d in delim:
                more_patterns.append(('meta.yaml',
                                      base1.format(set=s, checkname=cn, d=d),
                                      base2.format(set=s, checkname=cn, d=d)))

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
        with indir(recipe_dir):
            for f, p, n in self.patterns:
                p = eval_version(p)
                n = eval_version(n)
                replace_in_file(p, n, f)
            with open('meta.yaml', 'r') as f:
                text = f.read()
            # If we can't parse the meta_yaml then jump out
            meta_yaml = parsed_meta_yaml(text)
            # If the parser returns None, then we didn't read the meta.yaml
            # TODO: How we didn't fail at 01 on this recipe is mysterious
            if meta_yaml is None:
                attrs['bad'] = '{}: failed to read meta.yaml\n'.format($PROJECT)
                return False
            source_url = meta_yaml.get('source', {}).get('url')
            if not source_url:
                attrs['bad'] = '{}: missing url\n'.format($PROJECT)
                return False
            if isinstance(source_url, list):
                for url in source_url:
                    if 'Archive' not in url:
                        source_url = url
                        break
            if 'cran.r-project.org/src/contrib' in source_url:
                $VERSION = $VERSION.replace('_', '-')

        # now, update the feedstock to the new version
        source_url = eval_version(source_url)
        try:
            hash = hash_url(source_url, hash_type)
        except urllib.error.HTTPError:
            attrs['bad'] = '{}: hash failed at {}\n'.format(
                meta_yaml.get('package', {}).get('name', 'UNKOWN'), source_url)
            return False

        new_patterns = tuple(self.patterns) + tuple(self.more_patterns)
        with indir(recipe_dir), ${...}.swap(HASH_TYPE=hash_type, HASH=hash, SOURCE_URL=source_url):
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


class JS(Migrator):
    """Migrator for JavaScript syntax"""
    patterns = [('meta.yaml', '  script: npm install -g \.',
                 '  script: |\n'
                 '    tgz=$(npm pack)\n'
                 '    npm install -g $tgz'),
                # Fix our own error :(
                ('meta.yaml', '   script: |', '  script: |')]

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
                replace_in_file(p, n, f)
        return True

    def pr_body(self):
        body = super().pr_body()
        body.format('Notes and instructions for merging this PR:\n'
            '1. Please merge the PR only after the tests have passed. \n'
            "2. Feel free to push to the bot's branch to update this PR if needed. \n")

    def commit_message(self):
        return "migrated to new npm build"
