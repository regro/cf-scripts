import copy
import logging
import os.path
from typing import Any

from conda_forge_tick.contexts import ClonedFeedstockContext, FeedstockContext
from conda_forge_tick.migrators_types import AttrsTypedDict, MigrationUidTypedDict
from conda_forge_tick.utils import (
    get_bot_run_url,
    yaml_safe_dump,
    yaml_safe_load,
)

from .core import Migrator

logger = logging.getLogger(__name__)


def _file_contains(filename: str, string: str) -> bool:
    """Return whether the given file contains the given string."""
    with open(filename) as f:
        return string in f.read()


def _insert_subsection(
    filename: str,
    section: str,
    subsection: str,
    new_item: str,
) -> bool:
    """Append a new item onto the end of the section.subsection of a recipe."""
    # Strategy: Read the file as a list of strings. Split the file in half at the end of the
    # section.subsection section. Append the new_item to the first half. Combine the two
    # file halves. Write the file back to disk.
    first_half: list[str] = []
    second_half: list[str] = []
    break_located: bool = False
    section_found: bool = False
    subsection_found: bool = False
    with open(filename) as f:
        for line in f:
            if break_located:
                second_half.append(line)
            else:
                if line.startswith(section):
                    section_found = True
                elif section_found and line.lstrip().startswith(subsection):
                    subsection_found = True
                elif section_found and subsection_found:
                    if line.lstrip().startswith("-"):
                        # Inside section.subsection elements start with "-". We assume there
                        # is at least one item under section.subsection already.
                        first_half.append(line)
                        continue
                    else:
                        break_located = True
                        second_half.append(line)
                        continue
                first_half.append(line)

    if not break_located:
        # Don't overwrite file if we didn't find section.subsection
        return False

    with open(filename, "w") as f:
        f.writelines(first_half + [new_item] + second_half)

    return True


class AddNVIDIATools(Migrator):
    """Add the cf-nvidia-tools package to NVIDIA redist feedstocks."""

    name = "NVIDIA Tools Migrator"

    rerender = True

    migrator_version = 1

    allow_empty_commits = False

    allowed_schema_versions = [0]

    def filter_not_in_migration(self, attrs, not_bad_str_start=""):
        if super().filter_not_in_migration(attrs, not_bad_str_start):
            return True

        has_nvidia = False
        if "meta_yaml" in attrs and "source" in attrs["meta_yaml"]:
            if isinstance(attrs["meta_yaml"]["source"], list):
                src_list = attrs["meta_yaml"]["source"]
            else:
                src_list = [attrs["meta_yaml"]["source"]]
            for src in src_list:
                src_url = src.get("url", "") or ""
                has_nvidia = has_nvidia or (
                    "https://developer.download.nvidia.com" in src_url
                )

        return not has_nvidia

    def migrate(
        self, recipe_dir: str, attrs: AttrsTypedDict, **kwargs: Any
    ) -> MigrationUidTypedDict:
        """Perform the migration, updating the ``meta.yaml``.

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
        meta = os.path.join(recipe_dir, "meta.yaml")

        # STEP 0: Bump the build number
        self.set_build_number(meta)

        # STEP 1: Add cf-nvidia-tools to build requirements
        if _file_contains(meta, "cf-nvidia-tools"):
            logger.debug("cf-nvidia-tools already in meta.yaml; not adding again.")
        else:
            if _insert_subsection(
                meta,
                "requirements",
                "build",
                ["    - cf-nvidia-tools 1  # [linux]\n"],
            ):
                logger.debug("cf-nvidia-tools added to meta.yaml.")
            else:
                logger.warning(
                    "cf-nvidia-tools migration failed to add cf-nvidia-tools to meta.yaml. Manual migration required."
                )

        # STEP 2: Add check-glibc to the build script
        build = os.path.join(recipe_dir, "build.sh")
        if os.path.isfile(build):
            if _file_contains(build, "check-glibc"):
                logger.debug("build.sh already contains check-glibc; not adding again.")
            else:
                with open(build, "a") as file:
                    file.write(
                        '\ncheck-glibc "$PREFIX"/lib*/*.so.* "$PREFIX"/bin/* "$PREFIX"/targets/*/lib*/*.so.* "$PREFIX"/targets/*/bin/*\n'
                    )
                logger.debug("Added check-glibc to build.sh")
        else:
            if _file_contains(meta, "check-glibc"):
                logger.debug(
                    "meta.yaml already contains check-glibc; not adding again."
                )
            else:
                if _insert_subsection(
                    meta,
                    "requirements",
                    "build",
                    ["    - check-glibc  # [linux]\n"],
                ):
                    logger.debug("Added check-glibc to meta.yaml")
                else:
                    logger.warning(
                        "cf-nvidia-tools migration failed to add check-glibc to meta.yaml. Manual migration required."
                    )

        # STEP 3: Remove os_version keys from conda-forge.yml
        config = os.path.join(recipe_dir, "..", "conda-forge.yml")
        with open(config) as f:
            y = yaml_safe_load(f)
        y_orig = copy.deepcopy(y)
        y.pop("os_version", None)
        if y_orig != y:
            with open(config, "w") as f:
                yaml_safe_dump(y, f)

        return self.migrator_uid(attrs)

    def pr_title(self, feedstock_ctx: FeedstockContext) -> str:
        return "Add the cf-nvidia-tools package and run check-glibc"

    def pr_body(
        self, feedstock_ctx: ClonedFeedstockContext, add_label_text=True
    ) -> str:
        """Create a PR message body.

        Returns
        -------
        body
            The body of the PR message
        feedstock_ctx
            The current ClonedFeedstockContext
        """
        body = """\
In order to ensure that NVIDIA's redistributed binaries (redists) are being packaged
correctly, NVIDIA has created a package containing a collection of tools to perform
common actions for NVIDIA recipes.

At this time, the package may be used to check Linux binaries for their minimum glibc
requirement in order to ensure that the correct metadata is being used in the conda
package.

This migrator will attempt to add this glibc check to all feedstocks which download any
artifacts from https://developer.download.nvidia.com. The check involves adding
"cf-nvidia-tools" to the top-level build requirements and something like:

```bash
check-glibc "$PREFIX"/lib/*.so.* "$PREFIX"/bin/*
```

to the build script after the package artifacts have been installed.

> [!NOTE]
> A human needs to verify that the glob expression is checking all of the correct
> artifacts!

> [!NOTE]
> If the recipe does not have a top-level requirements.build section, it should be
> refactored so that the top-level package does not share a name with one of the
> outputs. i.e. The top-level package name should be something like "libcufoo-split".

More information about cf-nvidia-tools is available in the feedstock's [README](https://github.com/conda-forge/cf-nvidia-tools-feedstock/tree/main/recipe).

Please ping carterbox for questions.
"""

        body += "\n\n"

        if add_label_text:
            body += (
                "If this PR was opened in error or needs to be updated please add "
                "the `bot-rerun` label to this PR. The bot will close this PR and "
                "schedule another one. If you do not have permissions to add this "
                "label, you can use the phrase "
                "<code>@<space/>conda-forge-admin, please rerun bot</code> "
                "in a PR comment to have the `conda-forge-admin` add it for you.\n\n"
            )

        body += (
            "<sub>"
            "This PR was created by the [regro-cf-autotick-bot](https://github.com/regro/cf-scripts). "
            "The **regro-cf-autotick-bot** is a service to automatically "
            "track the dependency graph, migrate packages, and "
            "propose package version updates for conda-forge. "
            "Feel free to drop us a line if there are any "
            "[issues](https://github.com/regro/cf-scripts/issues)! "
            + f"This PR was generated by {get_bot_run_url()} - please use this URL for debugging."
            + "</sub>"
        )
        return body

    def commit_message(self, feedstock_ctx: FeedstockContext) -> str:
        """Create a commit message."""
        return "BLD: Try to automatically add cf-nvidia-tols and check glibc"

    def remote_branch(self, feedstock_ctx: FeedstockContext) -> str:
        """Branch to use on local and remote."""
        return "add-cf-nvidia-tools"
