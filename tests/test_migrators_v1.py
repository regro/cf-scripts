from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
from test_recipe_yaml_parsing import TEST_RECIPE_YAML_PATH

from conda_forge_tick.contexts import ClonedFeedstockContext
from conda_forge_tick.feedstock_parser import (
    parse_recipe_yaml,
    populate_feedstock_attributes,
)
from conda_forge_tick.migrators import (
    MigrationYaml,
    Migrator,
    MiniMigrator,
    Replacement,
    Version,
)
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.utils import frozen_to_json_friendly


class NoFilter:
    def filter(self, attrs, not_bad_str_start=""):
        return False


class _MigrationYaml(NoFilter, MigrationYaml):
    pass


yaml_rebuild = _MigrationYaml(yaml_contents="hello world", name="hi")
yaml_rebuild.cycles = []
yaml_rebuild_no_build_number = _MigrationYaml(
    yaml_contents="hello world",
    name="hi",
    bump_number=0,
)
yaml_rebuild_no_build_number.cycles = []


def requirements_from_yaml(reqs: list) -> set[str]:
    res = set()
    for req in reqs:
        if isinstance(req, dict):
            if "pin_compatible" in req:
                res.add(req["pin_compatible"]["name"])
            elif "pin_subpackage" in req:
                res.add(req["pin_subpackage"]["name"])
            else:
                # add if and else branch
                res |= set(req["then"])
                res |= set(req.get("else", []))
        else:
            res.add(req)

    return res


def run_test_yaml_migration(
    m, *, inp, output, kwargs, prb, mr_out, tmp_path, should_filter=False, is_v1=False
):
    recipe_path = tmp_path / "recipe"
    recipe_path.mkdir(exist_ok=True)

    with open(recipe_path / "recipe.yaml", "w") as f:
        f.write(inp)

    with pushd(tmp_path):
        subprocess.run(["git", "init"])
    # Load the recipe.yaml (this is done in the graph)
    try:
        pmy = parse_recipe_yaml(inp)
    except Exception:
        pmy = {}
    if pmy:
        pmy["version"] = pmy["package"]["version"]
        pmy["req"] = set()
        for k in ["build", "host", "run"]:
            reqs = requirements_from_yaml(pmy.get("requirements", {}).get(k, set()))
            pmy["req"] |= reqs
        try:
            pmy["recipe_yaml"] = parse_recipe_yaml(inp)
        except Exception:
            pmy["recipe_yaml"] = {}
    pmy["raw_meta_yaml"] = inp
    pmy.update(kwargs)

    assert m.filter(pmy) is should_filter
    if should_filter:
        return

    mr = m.migrate(str(recipe_path), pmy)
    assert mr_out == mr
    pmy["pr_info"] = {}
    pmy["pr_info"].update(PRed=[frozen_to_json_friendly(mr)])
    with open(recipe_path / "recipe.yaml") as f:
        actual_output = f.read()
    assert actual_output == output
    assert tmp_path.joinpath(".ci_support/migrations/hi.yaml").exists()
    with open(tmp_path / ".ci_support/migrations/hi.yaml") as f:
        saved_migration = f.read()
    assert saved_migration == m.yaml_contents


def sample_yaml_rebuild() -> str:
    yaml = TEST_RECIPE_YAML_PATH / "scipy_migrate.yaml"
    sample_yaml_rebuild = yaml.read_text()
    return sample_yaml_rebuild


def test_yaml_migration_rebuild(tmp_path):
    """Test that the build number is bumped"""
    sample = sample_yaml_rebuild()
    updated_yaml_rebuild = sample.replace("number: 0", "number: 1")

    run_test_yaml_migration(
        m=yaml_rebuild,
        inp=sample,
        output=updated_yaml_rebuild,
        kwargs={"feedstock_name": "scipy"},
        prb="This PR has been triggered in an effort to update **hi**.",
        mr_out={
            "migrator_name": yaml_rebuild.__class__.__name__,
            "migrator_version": yaml_rebuild.migrator_version,
            "name": "hi",
            "bot_rerun": False,
        },
        tmp_path=tmp_path,
        is_v1=True,
    )


def test_yaml_migration_rebuild_no_buildno(tmp_path):
    sample = sample_yaml_rebuild()

    run_test_yaml_migration(
        m=yaml_rebuild_no_build_number,
        inp=sample,
        output=sample,
        kwargs={"feedstock_name": "scipy"},
        prb="This PR has been triggered in an effort to update **hi**.",
        mr_out={
            "migrator_name": yaml_rebuild.__class__.__name__,
            "migrator_version": yaml_rebuild.migrator_version,
            "name": "hi",
            "bot_rerun": False,
        },
        tmp_path=tmp_path,
    )


##################################################################
# Run Matplotlib mini-migrator                               ###
##################################################################

version = Version(set())

matplotlib = Replacement(
    old_pkg="matplotlib",
    new_pkg="matplotlib-base",
    rationale=(
        "Unless you need `pyqt`, recipes should depend only on `matplotlib-base`."
    ),
    pr_limit=5,
)


class MockLazyJson:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


os.environ["RUN_URL"] = "hi world"


def run_test_migration(
    m: Migrator,
    inp: str,
    output: str,
    kwargs: dict,
    prb: str,
    mr_out: dict,
    tmp_path: Path,
    should_filter: bool = False,
    make_body: bool = False,
):
    if mr_out:
        mr_out.update(bot_rerun=False)

    Path(tmp_path).joinpath("recipe.yaml").write_text(inp)

    # read the conda-forge.yml
    cf_yml_path = Path(tmp_path).parent / "conda-forge.yml"
    cf_yml = cf_yml_path.read_text() if cf_yml_path.exists() else "{}"

    # Load the recipe.yaml (this is done in the graph)
    try:
        name = parse_recipe_yaml(inp)["package"]["name"]
    except Exception:
        name = "blah"

    pmy = populate_feedstock_attributes(
        name, sub_graph={}, recipe_yaml=inp, conda_forge_yaml=cf_yml
    )

    # these are here for legacy migrators
    pmy["version"] = pmy["recipe_yaml"]["package"]["version"]
    pmy["req"] = set()
    for k in ["build", "host", "run"]:
        reqs = requirements_from_yaml(pmy.get("requirements", {}).get(k, set()))
        pmy["req"] |= reqs
    pmy["raw_meta_yaml"] = inp
    pmy.update(kwargs)

    try:
        if "new_version" in kwargs:
            pmy["version_pr_info"] = {"new_version": kwargs["new_version"]}
        assert m.filter(pmy) == should_filter
    finally:
        pmy.pop("version_pr_info", None)
    if should_filter:
        return pmy

    m.run_pre_piggyback_migrations(
        tmp_path,
        pmy,
        hash_type=pmy.get("hash_type", "sha256"),
    )
    mr = m.migrate(tmp_path, pmy, hash_type=pmy.get("hash_type", "sha256"))
    m.run_post_piggyback_migrations(
        tmp_path,
        pmy,
        hash_type=pmy.get("hash_type", "sha256"),
    )

    if make_body:
        fctx = ClonedFeedstockContext(
            feedstock_name=name,
            attrs=pmy,
            local_clone_dir=Path(tmp_path),
        )
        m.effective_graph.add_node(name)
        m.effective_graph.nodes[name]["payload"] = MockLazyJson({})
        m.pr_body(fctx)

    assert mr_out == mr
    if not mr:
        return pmy

    pmy["pr_info"] = {}
    pmy["pr_info"].update(PRed=[frozen_to_json_friendly(mr)])
    with open(tmp_path / "recipe.yaml") as f:
        actual_output = f.read()

    # strip jinja comments
    pat = re.compile(r"{#.*#}")
    actual_output = pat.sub("", actual_output)
    output = pat.sub("", output)
    assert actual_output == output
    # TODO: fix subgraph here (need this to be xsh file)
    if isinstance(m, Version):
        pass
    else:
        assert prb in m.pr_body(None)
    try:
        if "new_version" in kwargs:
            pmy["version_pr_info"] = {"new_version": kwargs["new_version"]}
        assert m.filter(pmy) is True
    finally:
        pmy.pop("version_pr_info", None)

    return pmy


def run_minimigrator(
    migrator: MiniMigrator,
    inp: str,
    output: str,
    mr_out: dict,
    tmp_path: Path,
    should_filter: bool = False,
):
    if mr_out:
        mr_out.update(bot_rerun=False)
    recipe_path = tmp_path / "recipe"
    recipe_path.mkdir()
    with open(recipe_path / "recipe.yaml", "w") as f:
        f.write(inp)

    # read the conda-forge.yml
    if tmp_path.joinpath("conda-forge.yml").exists():
        with open(tmp_path / "conda-forge.yml") as fp:
            cf_yml = fp.read()
    else:
        cf_yml = "{}"

    # Load the recipe.yaml (this is done in the graph)
    try:
        name = parse_recipe_yaml(inp)["package"]["name"]
    except Exception:
        name = "blah"

    pmy = populate_feedstock_attributes(name, {}, inp, None, cf_yml)
    filtered = migrator.filter(pmy)
    if should_filter and filtered:
        return migrator
    assert filtered == should_filter

    with open(recipe_path / "recipe.yaml") as f:
        actual_output = f.read()
    # strip jinja comments
    pat = re.compile(r"{#.*#}")
    actual_output = pat.sub("", actual_output)
    output = pat.sub("", output)
    assert actual_output == output


def test_generic_replacement(tmp_path):
    sample_matplotlib = TEST_RECIPE_YAML_PATH / "sample_matplotlib.yaml"
    sample_matplotlib = sample_matplotlib.read_text()
    sample_matplotlib_correct = sample_matplotlib.replace(
        "    - matplotlib", "    - matplotlib-base"
    )
    # "recipe_yaml generic parsing not implemented yet" is raised here!
    with pytest.raises(NotImplementedError):
        run_test_migration(
            m=matplotlib,
            inp=sample_matplotlib,
            output=sample_matplotlib_correct,
            kwargs={},
            prb="I noticed that this recipe depends on `matplotlib` instead of ",
            mr_out={
                "migrator_name": "Replacement",
                "migrator_version": matplotlib.migrator_version,
                "name": "matplotlib-to-matplotlib-base",
            },
            tmp_path=tmp_path,
        )
