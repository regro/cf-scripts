Making Migrators
================
Migration is an important part of the regro-cf-autotick-bot's duties.
Migrations usually change how many feedstocks/packages operate, these can be
as simple as a yaml syntax change, or as complex as moving compiler stacks.
Most migrations are due to a change in the global pinning, as packages change
their pinning, the entire stack which depends directly on that package will
need to be updated.
This document will teach you how to create new migrators.

 .. note:: Unless you need to write a custom migrator, you should call for a migration using the ``conda-forge-pinning-feedstock``


Building a Migration YAML Using CFEP9
=====================================
For most migrations a migration can be created by adding a new migration yaml file in the ``recipe/migrations`` folder of ``conda-forge-pinning-feedstock`` and issuing a PR.
Once merged the migration will start.
You can copy the ``recipe/migrations/example.exyaml`` example and modify it similar to the staged-recipes example recipe.
Note that the ``migration_ts`` is the timestamp of the migration and can be created by copying the result of ``import time; print(time.time())`` from a python interpreter.

Please see the `CFEP9 implementation <https://github.com/conda-forge/conda-forge-enhancement-proposals/blob/master/cfep-09.md#implementation-details>`_ information for the
different kinds of migrations that are available.


Custom Migrations
=================

Custom migrators are used when

1. the internals of the conda-forge system (e.g., the various yaml configuration files)
   need to be changed
2. the migration task falls outside of CFGEP-09 (e.g., renaming a package, swapping
   a dependency, etc.)

To add a custom migration, follow the following steps.

Write your Custom Migration Class
---------------------------------
Your ``Migration`` instance should inherit from ``conda_forge_tick.migrations.core.Migration``.
You should implement the ``migrate`` method and override any other methods in order to make
a good looking pull request with a correct change to the feedstock.

Add your ``Migration`` to ``auto_tick.py``
------------------------------------------
To have the bot run the migration, we need to add the migrator to add it to the
``auto_tick`` module.
If the migrator needs no information about the graph (eg. version bumps) then
it can be added to the ``MIGRATORS`` list directly.
If the migrator needs graph information (eg it runs in topological order) then it
needs to be added by a function (e.g., ``add_rebuild``).
This function takes in the list of migrators and the entire package graph.
The job of the function is to pair down the graph to the nodes which need
to be migrated, for instance only packages which require ``python``.
This paired down graph is passed into the migrator, which is then added
to the migrators list.

Once the ``add_rebuild...`` function is created it needs to be added to the
``initialize_migrators`` function so the migration will go forward.

See the ``auto_tick.py`` file for example ``add_rebuild...`` functions.
