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
Building a new ``Rebuild`` Migrator takes two steps, building the migrator,
and adding it to ``auto_tick.xsh``.

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

Example of migrator addition function for openssl, for most simple re-pinning migration
one could replace ``openssl`` with the package which got pinned and things would work:

  .. code-block:: xonsh

    def add_rebuild_openssl(migrators, gx):
    """Adds rebuild openssl migrators.

    Parameters
    ----------
    migrators : list of Migrator
        The list of migrators to run.

    """

    total_graph = copy.deepcopy(gx)

    for node, attrs in gx.node.items():
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
    total_graph.remove_edges_from(total_graph.selfloop_edges())

    # everything which depends on openssl and has not predecessors in the 
    # openssl dependents graph
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
                cycles=cycles, obj_version=0)

