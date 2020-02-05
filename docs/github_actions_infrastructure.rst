GitHub Actions Infrastructure
=============================
The regro-cf-autotick-bot relies on GitHub Actions to enable the automatic
merging of its PRs. In the future, other key functionalities currently
performed by the bot may be moved to GitHub Actions as well.

Design
------
This service is structured as follows.

- The ``action.yml`` file, Docker image, and code that runs the bot are stored
  in the `cf-autotick-bot-action <https://github.com/regro/cf-autotick-bot-action>`_ repo.
- The GitHub Action always runs using the ``prod`` tag of the ``condaforge/rego-cf-autotick-bot-action``
  Docker container built from the repo. This container is set in the ``action.yml`` file.
- Feedstocks always use the ``action.yml`` file on the ``master`` branch of the
  ``regro/cf-autotick-bot-action`` repo. This configuration is set in ``conda-smithy``.
  A migration of all feedstocks would be required to change it.
- The GitHub events that trigger the action are also set in ``conda-smithy``.

Updating and Deploying the Action
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
You can push updates to any of the code in the ``master`` branch of the
``regro/cf-autotick-bot-action`` repo **except the action.yml file**. This
file is used globally by conda-forge and so changes to it should be considered
carefully. Once you have updated the code, you need to rebuild the Docker container.
Finally, tag your container as ``condaforge/rego-cf-autotick-bot-action:prod`` and push
it DockerHub. All GitHub Actions use this tag and so will see the updated code
as soon as the container is available.

Turning It All Off
^^^^^^^^^^^^^^^^^^
To turn off the GitHub Actions for all of ``conda-forge``, simply delete the
``condaforge/rego-cf-autotick-bot-action:prod`` container from DockerHub. This
will cause all of the actions on feedstocks that run with it to fail.


Automerging PRs
---------------
PRs from the regro-cf-autotick-bot are automatically merged when all of the
following conditions are met

1. all PR statuses must be passing, there must be at least one passing status, except maybe the linter
   (which is not fully reliable due to various bugs that need fixing)
2. the PR must be from the regro-cf-autotick-bot user
3. the feedstock must have ``bot: automerge: True`` set in the ``conda-forge.yml``
   If no key is set at all, it currently defaults to ``False`` but this may change.
4. the PR must have ``[bot-automerge]`` set in the title
5. the ``condaforge/rego-cf-autotick-bot-action:prod`` Docker image must exist
   on DockerHub

Opting Out of Automerge
^^^^^^^^^^^^^^^^^^^^^^^
Any feedstock can be opted-out of automerge by adding the following lines to
its ``conda-forge.yml``

.. code:: yaml

    bot:
      automerge: False

Currently, if these keys do not exist, the default is ``False``. This default
may change at some future date.

Turning On or Off Automerge for a Specific PR
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
To turn off automerge for a specific PR from the regro-cf-autotick-bot, simply
delete the ``[bot-automerge]`` slug from the PR title. Similarly, adding this
slug to the title of a PR from the regro-cf-autotick-bot will cause it to be
automatically merged when the conditions above are met.


Monitoring
----------
A small ``flask`` app running on ``heroku`` counts the number of completed
GitHub Actions across ``conda-forge``. The code for this app lives in the
`cf-action-counter <https://github.com/regro/cf-action-counter>`_ repo. This app
serves a `report <https://cf-action-counter.herokuapp.com/>`_ linked to the
``conda-forge`` `status webpage <https://conda-forge.org/status/>`_.
