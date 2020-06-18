Notes on the ``Version`` Migrator
=================================

The ``Version`` migrator uses a custom ``YAML`` parsing class for
``conda`` recipes in order to parse the recipe into a form that can be
algorithmically migrated without extensively using regex to change the recipe text
directly. This approach allows us to migrate more complicated recipes.

``YAML`` Parsing with Jinja2
----------------------------

We use ``ruamel.yaml`` and ``ruamel.yaml.jinja2`` to parse the recipe. These
packages ensure that comments (which can contain conda selectors) are kept. They
also ensure that any ``jinja2`` syntax is parsed correctly. Further, for
duplicate keys in the ``YAML``, but with different conda selectors, we collapse
the selector into the key. Finally, we use the ``jinja2`` AST to find all
simple ``jinja2`` ``set`` statements. These are parsed into a dictionary for later
use.

You can access the parser and parsed recipe via

.. code-block :: python

   from conda_forge_tick.recipe_parser import CondaMetaYAML

   cmeta = CondaMetaYAML(meta_yaml_as_string)

   # get the jinja2 vars
   for key, v in cmeta.jinja2_vars.items():
       print(key, v)

   # print a section of the recipe
   print(cmeta.meta["extra"])

Note that due to conda selectors and our need to deduplicate keys, any keys
with selectors will look like ``"source__###conda-selector###__win or osx"``.
You can access the middle token for selectors at ``conda_forge_tick.recipe_parser.CONDA_SELECTOR``.

It is useful to write generators if you want all keys possibly with selectors

.. code-block :: python

   def _gen_key_selector(dct: MutableMapping, key: str):
       for k in dct:
           if (
               k == key
               or (
                   CONDA_SELECTOR in k and
                   k.split(CONDA_SELECTOR)[0] == key
               )
           ):
               yield k

   for key in _gen_key_selector(cmeta.meta, "source"):
       print(cmeta.meta[key])


Version Migration Algorithm
---------------------------

Given the parser above, we migrate recipes via the following algorithm.

1. We compile all selectors in the recipe by recursively traversing
   the ``meta.yaml``. We also insert ``None`` into this set to represent no
   selector.
2. For each selector, we pull out all ``url``, hash-type key, and all ``jinja2``
   variables with the selector. If none with the selector are found, we default to
   any ones without a selector.
3. For each of the sets of items in step 2 above, we then try and update the
   version and get a new hash for the ``url``. We also try common variations
   in the ``url`` at this stage.
4. Finally, if we can find new hashes for all of the ``urls`` for each selector,
   we call the migration successful and submit a PR. Otherwise, no PR is submitted.
