Making Migrators
================
Migration is an important part of the regro-cf-autotick-bot's duties.
Migrations usually change how many feedstocks/packages operate, these can be
as simple as a yaml syntax change, or as complex as moving compiler stacks.
Most migrations are due to a change in the global pinning, as packages change
their pinning, the entire stack which depends directly on that package will
need to be updated.
This document will teach you how to create new migrators


Building a Migration
===========================
To build a ``Rebuild`` Migrator it must be added to ``auto_tick.xsh``.

Adding to ``auto_tick.xsh``
---------------------------
To have the bot run the migration we need to add the migrator to add it to the
``auto_tick`` module.
If the migrator needs no information about the graph (eg. version bumps) then
it can be added to the ``$MIGRATORS`` list directly.
If the migrator needs graph information (eg it runs in topo order) then it
needs to be added by a function (eg. ``add_rebuild``).
This function takes in the list of migrators and the entire package graph.
The job of the function is to pair down the graph to the nodes which need
to be migrated, for instance only packages which require ``python``.
This paired down graph is passed into the migrator, which is then added
to the migrators list.
Many times one can use the ``Rebuild`` class without having to create
a custom migrator.
Custom migrators are used when the internals of the conda-forge system (the various
yaml configuration files) need to be changed.

Example of migrator addition function:

  .. code-block:: xonsh

    def add_rebuild(migrators, gx):
    """Adds rebuild migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """

    # Make a copy of the graph so we don't delete things
    total_graph = copy.deepcopy(gx)

    # For each feedstock check the metadata we have
    for node, attrs in gx.node.items():
        meta_yaml = attrs.get("meta_yaml", {}) or {}
        bh = get_requirements(meta_yaml, run=False)

        # Check if python, compilers, openblas or r-base are in the recipe
        py_c = ('python' in bh and
                meta_yaml.get('build', {}).get('noarch') != 'python')
        com_c = (any([req.endswith('_compiler_stub') for req in bh]) or
                 any([a in bh for a in Compiler.compilers]))
        r_c = 'r-base' in bh
        ob_c = 'openblas' in bh

        # Extract the host, run and test deps
        rq = _host_run_test_dependencies(meta_yaml)

        # Remove packages from the graph which don't depend on the packages
        # that are being rebuilt, note that pluck does the right thing to
        # not remove links which are needed for topo order
        for e in list(total_graph.in_edges(node)):
            if e[0] not in rq:
                total_graph.remove_edge(*e)
        if not any([py_c, com_c, r_c, ob_c]):
            pluck(total_graph, node)

    # post plucking we can have several strange cases, lets remove all selfloops
    total_graph.remove_edges_from(total_graph.selfloop_edges())

    top_level = set(node for node in total_graph if not list(
        total_graph.predecessors(node)))

    # We extract the cycles because these cause problems with topo sorts
    # normally we build all the cycle packages at once and let the maintianers
    # deal with it
    cycles = list(nx.simple_cycles(total_graph))
    print('cycles are here:', cycles)

    migrators.append(
        CompilerRebuild(graph=total_graph,
                # Number of PRs an hour (try to keep to single digits so we
                # don't overload things
                pr_limit=5,
                name='Python 3.7, GCC 7, R 3.5.1, openBLAS 0.3.2',
                        top_level=top_level,
                        cycles=cycles))
