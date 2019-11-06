import copy
import json
import os
import time
import traceback
import logging

import datetime
from pprint import pprint
from urllib.error import URLError

from doctr.travis import run_command_hiding_token as doctr_run
import github3
import networkx as nx
import ruamel.yaml as yaml
from xonsh.lib.os import indir
from uuid import uuid4

from .git_utils import (get_repo, push_repo, is_github_api_limit_reached, ensure_label_exists, label_pr)
from .path_lengths import cyclic_topological_sort
from .utils import (setup_logger, pluck, get_requirements, load_graph, dump_graph, LazyJson)

logger = logging.getLogger("conda_forge_tick.auto_tick")

# TODO: move this back to the bot file as soon as the source issue is sorted
# https://travis-ci.org/regro/00-find-feedstocks/jobs/388387895#L1870
from .migrators import *
$MIGRATORS = [
   Version(pr_limit=30, piggy_back_migrations=[PipMigrator(), LicenseMigrator()]),
   # Noarch(pr_limit=10),
   # Pinning(pr_limit=1, removals={'perl'}),
   # Compiler(pr_limit=7),
]

BOT_RERUN_LABEL = {
    'name': 'bot-rerun',
    'color': '#191970',
    'description': 'Apply this label if you want the bot to retry issueing a particular pull-request'
}


def run(attrs, migrator, feedstock=None, protocol='ssh',
        pull_request=True, rerender=True, fork=True, gh=None,
        **kwargs):
    """For a given feedstock and migration run the migration

    Parameters
    ----------
    attrs: dict
        The node attributes
    migrator: Migrator instance
        The migrator to run on the feedstock
    feedstock : str, optional
        The feedstock to clone if None use $FEEDSTOCK
    protocol : str, optional
        The git protocol to use, defaults to ``ssh``
    pull_request : bool, optional
        If true issue pull request, defaults to true
    fork : bool
        If true create a fork, defaults to true
    gh : github3.GitHub instance, optional
        Object for communicating with GitHub, if None build from $USERNAME
        and $PASSWORD, defaults to None
    kwargs: dict
        The key word arguments to pass to the migrator

    Returns
    -------
    migrate_return: namedtuple
        The migration return dict used for tracking finished migrations
    pr_json: str
        The PR json object for recreating the PR as needed

    """
    # get the repo
    migrator.attrs = attrs
    feedstock_dir, repo = get_repo(attrs,
                                   branch=migrator.remote_branch(),
                                   feedstock=feedstock,
                                   protocol=protocol,
                                   pull_request=pull_request,
                                   fork=fork,
                                   gh=gh)

    recipe_dir = os.path.join(feedstock_dir, 'recipe')
    # if postscript/activate no noarch
    script_names = ['pre-unlink', 'post-link', 'pre-link', 'activate']
    exts = ['.bat', '.sh']
    no_noarch_files = [
        '{}.{}'.format(script_name, ext)
        for script_name in script_names for ext in exts
        ]
    if isinstance(migrator, Noarch) and any(
            x in os.listdir(recipe_dir) for x in no_noarch_files):
        rm -rf @(feedstock_dir)
        return False, False
    # migrate the `meta.yaml`
    migrate_return = migrator.migrate(recipe_dir, attrs, **kwargs)
    if not migrate_return:
        logger.critical("Failed to migrate %s, %s", $PROJECT, attrs.get('bad'))
        rm -rf @(feedstock_dir)
        return False, False

    # rerender, maybe
    diffed_files = []
    with indir(feedstock_dir), ${...}.swap(RAISE_SUBPROC_ERROR=False):
        git commit -am @(migrator.commit_message())
        if rerender:
            head_ref = $(git rev-parse HEAD).strip()
            logger.info('Rerendering the feedstock')
            conda smithy rerender -c auto
            # If we tried to run the MigrationYaml and rerender did nothing (we only
            # bumped the build number and dropped a yaml file in migrations) bail
            # for instance platform specific migrations
            diffed_files = [_ for _ in $(git diff --name-only @(head_ref)...HEAD).split() if not (_.startswith('recipe') or _.startswith('migrators') or _.startswith('README'))]

    if isinstance(migrator, MigrationYaml) and not diffed_files:
        # spoof this so it looks like the package is done
        pr_json = {'state': 'closed', 'merged_at': 'never issued', 'id': str(uuid4())}
        ljpr = LazyJson(os.path.join($PRJSON_DIR, str(pr_json['id']) + '.json'))
        ljpr.update(**pr_json)
    else:
        # push up
        try:
            pr_json = push_repo(feedstock_dir,
                                migrator.pr_body(),
                                repo,
                                migrator.pr_title(),
                                migrator.pr_head(),
                                migrator.remote_branch())

        # This shouldn't happen too often any more since we won't double PR
        except github3.GitHubError as e:
            if e.msg != 'Validation Failed':
                raise
            else:
                print(f'Error during push {e}')
                # If we just push to the existing PR then do nothing to the json
                pr_json = False

    # If we've gotten this far then the node is good
    attrs['bad'] = False
    logger.info('Removing feedstock dir')
    rm -rf @(feedstock_dir)
    return migrate_return, pr_json


def _requirement_names(reqlist):
    """Parse requirement names from a list ignoring `None`
    """
    return [r.split()[0] for r in reqlist if r is not None]


def _host_run_test_dependencies(meta_yaml):
    """Parse the host/run/test dependencies of a recipe

    This function parses top-level and `outputs` requirements sections.

    The complicated logic here is mainly to support not including a
    `host` section, and using `build` instead.
    """
    rq = set()
    for block in [meta_yaml] + meta_yaml.get("outputs", []) or []:
        req = block.get("requirements", {}) or {}
        # output requirements given as list (e.g. openmotif)
        if isinstance(req, list):
            rq.update(_requirement_names(req))
            continue

        # if there is a host and it has things; use those
        if req.get('host'):
            rq.update(_requirement_names(req.get('host')))
        # there is no host; look at build
        elif req.get("host", "no host") not in [None, []]:
            rq.update(_requirement_names(req.get('build', []) or []))
        rq.update(_requirement_names(req.get('run', []) or []))

    # add testing dependencies
    for key in ('requirements', 'requires'):
        rq.update(_requirement_names(
            meta_yaml.get('test', {}).get(key, []) or []
        ))

    return rq


def add_rebuild(migrators, gx):
    """Adds rebuild migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """

    total_graph = copy.deepcopy(gx)
    for node, node_attrs in gx.nodes.items():
        attrs = node_attrs['payload']
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        bh = get_requirements(meta_yaml, run=False)

        py_c = ('python' in bh and
                meta_yaml.get('build', {}).get('noarch') != 'python')
        com_c = (any([req.endswith('_compiler_stub') for req in bh]) or
                 any([a in bh for a in Compiler.compilers]))
        r_c = 'r-base' in bh
        ob_c = 'openblas' in bh

        rq = _host_run_test_dependencies(meta_yaml)

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([py_c, com_c, r_c, ob_c]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = set(node for node in total_graph if not list(
        total_graph.predecessors(node)))
    cycles = list(nx.simple_cycles(total_graph))
    # print('cycles are here:', cycles)

    migrators.append(
        Rebuild(graph=total_graph,
                pr_limit=5,
                name='Python 3.7, GCC 7, R 3.5.1, openBLAS 0.3.2',
                        top_level=top_level,
                        cycles=cycles))


def add_rebuild_openssl(migrators, gx):
    """Adds rebuild openssl migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """

    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        attrs = node_attrs['payload']
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        bh = get_requirements(meta_yaml)
        openssl_c = 'openssl' in bh

        rq = _host_run_test_dependencies(meta_yaml)

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([openssl_c]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = {node for node in gx.successors("openssl") if
                 (node in total_graph) and
                 len(list(total_graph.predecessors(node))) == 0}
    cycles = list(nx.simple_cycles(total_graph))
    # print('cycles are here:', cycles)

    migrators.append(
        Rebuild(graph=total_graph,
                pr_limit=5,
                name='OpenSSL',
                top_level=top_level,
                cycles=cycles, obj_version=3))


def add_rebuild_libprotobuf(migrators, gx):
    """Adds rebuild libprotobuf migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """

    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        attrs = node_attrs['payload']
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        bh = get_requirements(meta_yaml)
        protobuf_c = 'libprotobuf' in bh

        rq = _host_run_test_dependencies(meta_yaml)

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([protobuf_c]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = {node for node in gx.successors("libprotobuf") if
                 (node in total_graph) and
                 len(list(total_graph.predecessors(node))) == 0}
    cycles = list(nx.simple_cycles(total_graph))
    # print('cycles are here:', cycles)

    migrators.append(
        Rebuild(graph=total_graph,
                pr_limit=5,
                name='libprotobuf-3.7',
                top_level=top_level,
                cycles=cycles, obj_version=3))


def add_rebuild_successors(migrators, gx, package_name, pin_version, pr_limit=5, obj_version=0, rebuild_class=Rebuild):
    """Adds rebuild migrator.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.
    gx : networkx.DiGraph
        The feedstock graph
    package_name : str
        The package who's pin was moved
    pin_version : str
        The new pin value
    pr_limit : int, optional
        The number of PRs per hour, defaults to 5
    obj_version : int, optional
        The version of the migrator object (useful if there was an error)
        defaults to 0
    """

    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        attrs = node_attrs['payload']
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        bh = get_requirements(meta_yaml)
        criteria = package_name in bh

        rq = _host_run_test_dependencies(meta_yaml)

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([criteria]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = {node for node in gx.successors(package_name) if
                 (node in total_graph) and
                 len(list(total_graph.predecessors(node))) == 0}
    cycles = list(nx.simple_cycles(total_graph))
    # print('cycles are here:', cycles)

    migrators.append(
        rebuild_class(graph=total_graph,
                pr_limit=pr_limit,
                name=f'{package_name}-{pin_version}',
                top_level=top_level,
                cycles=cycles, obj_version=obj_version))


def add_rebuild_blas(migrators, gx):
    """Adds rebuild blas 2.0 migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """
    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        attrs = node_attrs['payload']
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        bh = get_requirements(meta_yaml)
        pkgs = set(["openblas", "openblas-devel", "mkl", "mkl-devel", "blas", "lapack", "clapack"])
        blas_c = len(pkgs.intersection(bh)) > 0

        rq = _host_run_test_dependencies(meta_yaml)

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([blas_c]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = set(node for node in total_graph if not list(
        total_graph.predecessors(node)))
    cycles = list(nx.simple_cycles(total_graph))

    migrators.append(
        BlasRebuild(graph=total_graph,
                pr_limit=5,
                name='blas-2.0',
                top_level=top_level,
                cycles=cycles, obj_version=0))


def add_arch_migrate(migrators, gx):
    """Adds rebuild migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """
    total_graph = copy.deepcopy(gx)

    for node, node_attrs in gx.nodes.items():
        attrs = node_attrs['payload']
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        # no need to consider noarch packages for this rebuild
        noarch = meta_yaml.get('build', {}).get('noarch')
        if noarch:
            pluck(total_graph, node)
        # since we aren't building the compilers themselves, remove
        if node.endswith('_compiler_stub'):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = {node for node in total_graph if not set(total_graph.predecessors(node))}
    cycles = list(nx.simple_cycles(total_graph))
    # print('cycles are here:', cycles)

    migrators.append(
        ArchRebuild(graph=total_graph,
                pr_limit=5,
                name='aarch64 and ppc64le addition',
                        top_level=top_level,
                        cycles=cycles))


def add_rebuild_migration_yaml(migrators, gx, package_names, config={},
                               migration_name="", pr_limit=5):
    """Adds rebuild migrator.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.
    gx : networkx.DiGraph
        The feedstock graph
    package_names : list of str
        The package who's pin was moved
    config: dict
        The __migrator contents of the migration
    migration_name: str
        Name of the migration
    pr_limit : int, optional
        The number of PRs per hour, defaults to 5
    """

    total_graph = copy.deepcopy(gx)

    obj_version = config.get('migration_number', 0)

    for node, node_attrs in gx.nodes.items():
        attrs = node_attrs['payload']
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        if ('strong' in meta_yaml.get('build', {}) or 
            any(['strong' in output.get('build', {}) for output in meta_yaml.get('outputs', []) if output.get('build')])):
            bh = get_requirements(meta_yaml, run=False)
        else:
            bh = (get_requirements(meta_yaml, run=False, build=False, host=True) or 
                  get_requirements(meta_yaml, build=True, run=False, host=False))
        criteria = any(package_name in bh for package_name in package_names) and ('noarch' not in meta_yaml.get('build', {}))

        rq = _host_run_test_dependencies(meta_yaml)

        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([criteria]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(nx.selfloop_edges(total_graph))

    top_level = {node for node in set(gx.successors(package_name) for package_name in package_names) if
                 (node in total_graph) and
                 len(list(total_graph.predecessors(node))) == 0}
    cycles = list(nx.simple_cycles(total_graph))
    migrator = MigrationYaml(config,
                  graph=total_graph,
                  pr_limit=pr_limit,
                  name=migration_name,
                  top_level=top_level,
                  cycles=cycles, obj_version=obj_version, 
                  piggy_back_migrations=[PipMigrator(), LicenseMigrator()])
    print(f'bump number is {migrator.bump_number}')
    migrators.append(migrator)


def migration_factory(migrators, gx, pr_limit=50):
    migration_yamls = []
    with indir('../conda-forge-pinning-feedstock/recipe/migrations'):
        for yaml_file in g`*.y*ml`:
            with open(yaml_file) as f:
                yaml_contents = f.read()
            migration_yamls.append((yaml_file, yaml_contents))
    for yaml_file, yaml_contents in migration_yamls:
        loaded_yaml = yaml.safe_load(yaml_contents)
        print(os.path.splitext(yaml_file)[0])
        yaml_config = loaded_yaml.get('__migrator', {})
        exclude_packages = set(yaml_config.get('exclude', []))
        package_names = ((set(loaded_yaml) | set(l.replace('_', '-') for l in loaded_yaml)) & set(
            gx.nodes)) - exclude_packages
        add_rebuild_migration_yaml(
            migrators, gx, package_names,
            migration_name=os.path.splitext(yaml_file)[0], config=yaml_config,
            pr_limit=pr_limit
        )


def initialize_migrators(do_rebuild=False):
    setup_logger(logger)
    temp = g`/tmp/*`
    gx = load_graph()
    $GRAPH = gx
    $REVER_DIR = './feedstocks/'
    $REVER_QUIET = True
    $PRJSON_DIR = 'pr_json'

    smithy_version = ![conda smithy --version].output.strip()
    pinning_version = json.loads(![conda list conda-forge-pinning --json].output.strip())[0]['version']

    add_arch_migrate($MIGRATORS, gx)
    add_rebuild_successors($MIGRATORS, gx, 'qt', '5.12', pr_limit=5)
    # migration_factory($MIGRATORS, gx)
    for m in $MIGRATORS:
        print(f'{getattr(m, "name", m)} graph size: {len(getattr(m, "graph", []))}')

    return gx, smithy_version, pinning_version, temp, $MIGRATORS


def get_effective_graph(migrator: Migrator, gx):
    gx2 = copy.deepcopy(getattr(migrator, 'graph', gx))

    # Prune graph to only things that need builds right now
    for node, node_attrs in gx.nodes.items():
        attrs = node_attrs['payload']
        if node in gx2 and migrator.filter(attrs):
            gx2.remove_node(node)

    return gx2


def migrator_status(migrator: Migrator, gx):
    """Gets the migrator progress for a given migrator

    Returns
    -------
    out : dict
        Dictionary of statuses with the feedstocks in them
    order :
        Build order for this migrator
    """
    out = {
        'done': set(),
        'in-pr': set(),
        'awaiting-pr': set(),
        'awaiting-parents': set(),
        'bot-error': set(),
    }

    gx2 = copy.deepcopy(getattr(migrator, 'graph', gx))

    top_level = set(node for node in gx2 if not list(gx2.predecessors(node)))
    build_sequence = list(cyclic_topological_sort(gx2, top_level))

    feedstock_metadata = dict()

    import graphviz
    from streamz.graph import _clean_text
    gv = graphviz.Digraph()
    for node, node_attrs in gx2.nodes.items():
        attrs = node_attrs['payload']
        # remove archived from status
        if attrs.get('archived', False):
            continue
        node_metadata = {}
        feedstock_metadata[node] = node_metadata
        nuid = migrator.migrator_uid(attrs)
        for pr_json in attrs.get('PRed', []):
            if pr_json and pr_json['data'] == frozen_to_json_friendly(nuid)['data']:
                break
        else:
            pr_json = None

        # No PR was ever issued but the migration was performed.
        # This is only the case when the migration was done manually before the bot could issue any PR.
        manually_done = pr_json is None and frozen_to_json_friendly(nuid)['data'] in (z['data'] for z in attrs.get('PRed', []))

        buildable = not migrator.filter(attrs)
        fntc = 'black'
        if manually_done:
            out['done'].add(node)
            fc = '#440154'
            fntc = 'white'
        elif pr_json is None:
            if buildable:
                out['awaiting-pr'].add(node)
                fc = '#35b779'
            else:
                out['awaiting-parents'].add(node)
                fc = '#fde725'
        elif 'PR' not in pr_json:
            out['bot-error'].add(node)
            fc = '#000000'
            fntc = 'white'
        elif pr_json['PR']['state'] == 'closed':
            out['done'].add(node)
            fc = '#440154'
            fntc = 'white'
        else:
            out['in-pr'].add(node)
            fc = '#31688e'
            fntc = 'white'
        if node not in out['done']:
            gv.node(node, label=_clean_text(node), fillcolor=fc, style='filled', fontcolor=fntc)

        # additional metadata for reporting
        node_metadata['num_descendants'] = len(nx.descendants(gx2, node))
        node_metadata['immediate_children'] = [k for k in sorted(gx2.successors(node)) if not gx2[k].get('payload', {}).get('archived', False)]
        if pr_json and 'PR' in pr_json:
            # I needed to fake some PRs they don't have html_urls though
            node_metadata['pr_url'] = pr_json['PR'].get('html_url', '')

    for k in out.keys():
        out[k] = list(sorted(out[k], key=lambda x: build_sequence.index(x) if x in build_sequence else -1))

    out['_feedstock_status'] = feedstock_metadata
    for (e0, e1), edge_attrs in gx2.edges.items():
        if e0 not in out['done'] and e1 not in out['done'] and not gx2.nodes[e0]['payload'].get('archived', False) and not gx2.nodes[e1]['payload'].get('archived', False):
            gv.edge(e0, e1)

    return out, build_sequence, gv


def main(args=None):
    gh = github3.login($USERNAME, $PASSWORD)
    gx, smithy_version, pinning_version, temp, $MIGRATORS = initialize_migrators(False)

    for migrator in $MIGRATORS:
        good_prs = 0
        effective_graph = get_effective_graph(migrator, gx)

        $SUBGRAPH = effective_graph
        logger.info('Total migrations for %s: %d', migrator.__class__.__name__,
                    len(effective_graph.nodes))

        top_level = set(node for node in effective_graph if not list(effective_graph.predecessors(node)))
        # print(list(migrator.order(effective_graph, gx)))
        for node_name in migrator.order(effective_graph, gx):
            with gx.nodes[node_name]['payload'] as attrs:
                # Don't let travis timeout, break ahead of the timeout so we make certain
                # to write to the repo
                if time.time() - int($START_TIME) > int($TIMEOUT) or good_prs >= migrator.pr_limit:
                    break
                $PROJECT = attrs['feedstock_name']
                $NODE = node_name
                logger.info('%s IS MIGRATING %s', migrator.__class__.__name__.upper(),
                            $PROJECT)
                try:
                    # Don't bother running if we are at zero
                    if gh.rate_limit()['resources']['core']['remaining'] == 0:
                        break
                    rerender = (attrs.get('smithy_version') != smithy_version or
                                attrs.get('pinning_version') != pinning_version or
                                migrator.rerender)
                    migrator_uid, pr_json = run(attrs=attrs, migrator=migrator, gh=gh,
                                                rerender=rerender, protocol='https',
                                                hash_type=attrs.get('hash_type', 'sha256'))
                    # if migration successful
                    if migrator_uid:
                        d = frozen_to_json_friendly(migrator_uid)
                        # if we have the PR already do nothing
                        if d['data'] in [existing_pr['data'] for existing_pr in attrs.get('PRed', [])]:
                            pass
                        else:
                            if not pr_json:
                                pr_json = {
                                'state': 'closed',
                                'head': {'ref': '<this_is_not_a_branch>'}
                            }
                            d.update(PR=pr_json)
                            attrs.setdefault('PRed', []).append(d)
                        attrs.update(
                            {'smithy_version': smithy_version,
                             'pinning_version': pinning_version})

                except github3.GitHubError as e:
                    if e.msg == 'Repository was archived so is read-only.':
                        attrs['archived'] = True
                    else:
                        logger.critical('GITHUB ERROR ON FEEDSTOCK: %s', $PROJECT)
                        if is_github_api_limit_reached(e, gh):
                            break
                except URLError as e:
                    logger.exception('URLError ERROR')
                    attrs['bad'] = {
                        'exception': str(e),
                        'traceback': str(traceback.format_exc()).split('\n'),
                        'code': getattr(e, 'code'),
                        'url': getattr(e, 'url'),
                    }
                except Exception as e:
                    logger.exception('NON GITHUB ERROR')
                    attrs['bad'] = {
                        'exception': str(e),
                        'traceback': str(traceback.format_exc()).split('\n')
                    }
                else:
                    if migrator_uid:
                        # On successful PR add to our counter
                        good_prs += 1
                finally:
                    # Write graph partially through
                    dump_graph(gx)
                    rm -rf $REVER_DIR + '/*'
                    logger.info(![pwd])
                    for f in g`/tmp/*`:
                        if f not in temp:
                            rm -rf @(f)

    logger.info('API Calls Remaining: %d', gh.rate_limit()['resources']['core']['remaining'])
    logger.info('Done')


if __name__ == "__main__":
    main()
