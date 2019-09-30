Usage Docs
==========

These docs aim to provide information about how to use ``conda_forge_tick`` to interact with ``cf-graph-countyfair``.
Note that you will need a copy of ``regro/cf-graph-countyfair`` and ``conda-forge/conda-forge-pinning-feedstock`` in the same directory for this to work properly, both can be found on github.

Loading the graph
+++++++++++++++++
To load the feedstock graph use the ``load_graph`` function

 .. code-block:: python

 from conda_forge_tick.utils import load_graph
 gx = load_graph()


Note that all nodes in the graph are backed by ``LazyJson`` objects associated with the ``payload`` key which allow for lazy loading of the node attributes.

 .. code-block:: python

 print(dict(gx.node['python']['payload']))


Calculating migration impact
++++++++++++++++++++++++++++
The number of feedstocks which would be migrated by a particular migration can be calculated:

 .. code-block:: python
 from conda_forge_tick.auto_tick import initialize_migrators
 *_, migrators = initialize_migrators()
 migrator = migrators[-1]
 print(migrator.name)
 graph = migrator.graph
 # number of packages in the graph to be migrated
 print(len(graph))

This is an important number to know when proposing a migration
