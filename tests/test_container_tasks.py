import copy
import glob
import json
import logging
import os
import pprint
import shutil
import subprocess
import tempfile

import conda_smithy
import networkx as nx
import pytest
from conda.models.version import VersionOrder
from conda_forge_feedstock_ops.container_utils import (
    get_default_log_level_args,
    run_container_operation,
)
from conda_forge_feedstock_ops.os_utils import get_user_execute_permissions
from test_migrators import sample_yaml_rebuild, updated_yaml_rebuild

from conda_forge_tick.feedstock_parser import (
    load_feedstock_containerized,
    populate_feedstock_attributes,
)
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    dumps,
    lazy_json_override_backends,
)
from conda_forge_tick.migration_runner import run_migration_containerized
from conda_forge_tick.migrators import MigrationYaml, Version
from conda_forge_tick.os_utils import pushd
from conda_forge_tick.provide_source_code import (
    provide_source_code_containerized,
    provide_source_code_local,
)
from conda_forge_tick.rerender_feedstock import rerender_feedstock
from conda_forge_tick.solver_checks import is_recipe_solvable
from conda_forge_tick.update_recipe.version import update_version_feedstock_dir
from conda_forge_tick.update_upstream_versions import (
    all_version_sources,
    get_latest_version_containerized,
)
from conda_forge_tick.utils import (
    frozen_to_json_friendly,
    parse_meta_yaml,
    parse_meta_yaml_containerized,
)

TOTAL_GRAPH = nx.DiGraph()
TOTAL_GRAPH.graph["outputs_lut"] = {}
VERSION = Version(set(), total_graph=TOTAL_GRAPH)

YAML_PATH = os.path.join(os.path.dirname(__file__), "test_yaml")

HAVE_CONTAINERS = (
    shutil.which("docker") is not None
    and subprocess.run(["docker", "--version"], capture_output=True).returncode == 0
)

if HAVE_CONTAINERS:
    HAVE_TEST_IMAGE = False
    try:
        for line in subprocess.run(
            [
                "docker",
                "images",
                "--format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines():
            image = json.loads(line)
            if image["Repository"] == "conda-forge-tick" and image["Tag"] == "test":
                HAVE_TEST_IMAGE = True
                break
    except subprocess.CalledProcessError as e:
        print(
            f"Could not list local docker images due "
            f"to error {e}. Skipping container tests!"
        )


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_get_latest_version(use_containers):
    data = run_container_operation(
        [
            "conda-forge-tick-container",
            "get-latest-version",
            "--existing-feedstock-node-attrs",
            "conda-smithy",
        ]
        + get_default_log_level_args(logging.getLogger("conda_forge_tick")),
    )
    assert VersionOrder(data["new_version"]) >= VersionOrder(conda_smithy.__version__)


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_get_latest_version_json(use_containers):
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(tmpdir),
        lazy_json_override_backends(["github"], use_file_cache=False),
        LazyJson("node_attrs/conda-smithy.json") as lzj,
    ):
        existing_feedstock_node_attrs = dumps(lzj.data)

        data = run_container_operation(
            [
                "conda-forge-tick-container",
                "get-latest-version",
                "--existing-feedstock-node-attrs",
                existing_feedstock_node_attrs,
            ]
            + get_default_log_level_args(logging.getLogger("conda_forge_tick")),
        )
        assert VersionOrder(data["new_version"]) >= VersionOrder(
            conda_smithy.__version__
        )


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_get_latest_version_containerized(use_containers):
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(tmpdir),
        lazy_json_override_backends(["github"], use_file_cache=False),
        LazyJson("node_attrs/conda-smithy.json") as lzj,
    ):
        attrs = copy.deepcopy(lzj.data)

        data = get_latest_version_containerized(
            "conda-smithy", attrs, all_version_sources()
        )
        assert VersionOrder(data["new_version"]) >= VersionOrder(
            conda_smithy.__version__
        )


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_get_latest_version_containerized_mpas_tools(use_containers):
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(tmpdir),
        lazy_json_override_backends(["github"], use_file_cache=False),
        LazyJson("node_attrs/mpas_tools.json") as lzj,
    ):
        attrs = copy.deepcopy(lzj.data)

        data = get_latest_version_containerized(
            "mpas_tools", attrs, all_version_sources()
        )
        assert data["new_version"] is not False


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_parse_feedstock(use_containers):
    with tempfile.TemporaryDirectory() as tmpdir, pushd(tmpdir):
        data = run_container_operation(
            [
                "conda-forge-tick-container",
                "parse-feedstock",
                "--existing-feedstock-node-attrs",
                "conda-smithy",
            ]
            + get_default_log_level_args(logging.getLogger("conda_forge_tick")),
        )

        with (
            lazy_json_override_backends(["github"], use_file_cache=False),
            LazyJson("node_attrs/conda-smithy.json") as lzj,
        ):
            attrs = copy.deepcopy(lzj.data)

        assert data["feedstock_name"] == attrs["feedstock_name"]
        assert not data["parsing_error"]


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_parse_feedstock_json(use_containers):
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(tmpdir),
        lazy_json_override_backends(["github"], use_file_cache=False),
        LazyJson("node_attrs/conda-smithy.json") as lzj,
    ):
        attrs = copy.deepcopy(lzj.data)
        existing_feedstock_node_attrs = dumps(lzj.data)

        data = run_container_operation(
            [
                "conda-forge-tick-container",
                "parse-feedstock",
                "--existing-feedstock-node-attrs",
                existing_feedstock_node_attrs,
            ]
            + get_default_log_level_args(logging.getLogger("conda_forge_tick")),
        )
        assert data["feedstock_name"] == attrs["feedstock_name"]
        assert not data["parsing_error"]


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_load_feedstock_containerized(use_containers):
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(tmpdir),
        lazy_json_override_backends(["github"], use_file_cache=False),
        LazyJson("node_attrs/conda-smithy.json") as lzj,
    ):
        attrs = copy.deepcopy(lzj.data)

        data = load_feedstock_containerized("conda-smithy", attrs)
        assert data["feedstock_name"] == attrs["feedstock_name"]
        assert not data["parsing_error"]


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_load_feedstock_containerized_mpas_tools(use_containers):
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(tmpdir),
        lazy_json_override_backends(["github"], use_file_cache=False),
        LazyJson("node_attrs/mpas_tools.json") as lzj,
    ):
        attrs = copy.deepcopy(lzj.data)

        data = load_feedstock_containerized("mpas_tools", attrs)
        assert data["feedstock_name"] == attrs["feedstock_name"]
        assert not data["parsing_error"]
        assert data["raw_meta_yaml"] == attrs["raw_meta_yaml"]


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_parse_meta_yaml_containerized(use_containers):
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(tmpdir),
        lazy_json_override_backends(["github"], use_file_cache=False),
        LazyJson("node_attrs/conda-smithy.json") as lzj,
    ):
        attrs = copy.deepcopy(lzj.data)

        data = parse_meta_yaml_containerized(
            attrs["raw_meta_yaml"],
        )
        assert data["package"]["name"] == "conda-smithy"


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_rerender_feedstock_containerized_same_as_local(
    use_containers, capfd
):
    with (
        tempfile.TemporaryDirectory() as tmpdir_cont,
        tempfile.TemporaryDirectory() as tmpdir_local,
    ):
        assert tmpdir_cont != tmpdir_local

        with pushd(tmpdir_cont):
            subprocess.run(
                [
                    "git",
                    "clone",
                    "https://github.com/conda-forge/conda-forge-feedstock-check-solvable-feedstock.git",
                ]
            )
            # make sure rerender happens
            with pushd("conda-forge-feedstock-check-solvable-feedstock"):
                cmds = [
                    ["git", "rm", "-f", ".gitignore"],
                    ["git", "rm", "-rf", ".scripts"],
                    ["git", "config", "user.email", "conda@conda.conda"],
                    ["git", "config", "user.name", "conda c. conda"],
                    ["git", "commit", "-m", "test commit"],
                ]
                for cmd in cmds:
                    subprocess.run(
                        cmd,
                        check=True,
                    )

            try:
                msg = rerender_feedstock(
                    os.path.join(
                        tmpdir_cont, "conda-forge-feedstock-check-solvable-feedstock"
                    ),
                    use_container=True,
                )
            finally:
                captured = capfd.readouterr()
                print(f"out: {captured.out}\nerr: {captured.err}")

            if "git commit -m " in captured.err:
                assert msg is not None, (
                    f"msg: {msg}\nout: {captured.out}\nerr: {captured.err}"
                )
                assert msg.startswith("MNT:"), (
                    f"msg: {msg}\nout: {captured.out}\nerr: {captured.err}"
                )
            else:
                assert msg is None, (
                    f"msg: {msg}\nout: {captured.out}\nerr: {captured.err}"
                )

        with pushd(tmpdir_local):
            subprocess.run(
                [
                    "git",
                    "clone",
                    "https://github.com/conda-forge/conda-forge-feedstock-check-solvable-feedstock.git",
                ]
            )
            # make sure rerender happens
            with pushd("conda-forge-feedstock-check-solvable-feedstock"):
                cmds = [
                    ["git", "rm", "-f", ".gitignore"],
                    ["git", "rm", "-rf", ".scripts"],
                    ["git", "config", "user.email", "conda@conda.conda"],
                    ["git", "config", "user.name", "conda c. conda"],
                    ["git", "commit", "-m", "test commit"],
                ]
                for cmd in cmds:
                    subprocess.run(
                        cmd,
                        check=True,
                    )

            try:
                local_msg = rerender_feedstock(
                    os.path.join(
                        tmpdir_local, "conda-forge-feedstock-check-solvable-feedstock"
                    ),
                    use_container=False,
                )
            finally:
                local_captured = capfd.readouterr()
                print(f"out: {local_captured.out}\nerr: {local_captured.err}")

        assert msg == local_msg

        # now compare files
        cont_fnames = set(
            glob.glob(os.path.join(tmpdir_cont, "**", "*"), recursive=True)
        )
        local_fnames = set(
            glob.glob(os.path.join(tmpdir_local, "**", "*"), recursive=True)
        )

        rel_cont_fnames = {os.path.relpath(fname, tmpdir_cont) for fname in cont_fnames}
        rel_local_fnames = {
            os.path.relpath(fname, tmpdir_local) for fname in local_fnames
        }
        assert rel_cont_fnames == rel_local_fnames, (
            f"{rel_cont_fnames} != {rel_local_fnames}"
        )

        for cfname in cont_fnames:
            lfname = os.path.join(tmpdir_local, os.path.relpath(cfname, tmpdir_cont))
            if not os.path.isdir(cfname):
                with open(cfname, "rb") as f:
                    cdata = f.read()
                with open(lfname, "rb") as f:
                    ldata = f.read()
                assert cdata == ldata, f"{cfname} not equal to local"


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_rerender_feedstock_containerized_empty(use_containers):
    with tempfile.TemporaryDirectory() as tmpdir_local:
        # first run the rerender locally
        with pushd(tmpdir_local):
            subprocess.run(
                [
                    "git",
                    "clone",
                    "https://github.com/conda-forge/conda-forge-feedstock-check-solvable-feedstock.git",
                ]
            )
            # make sure rerender happens
            with pushd("conda-forge-feedstock-check-solvable-feedstock"):
                cmds = [
                    ["git", "rm", "-f", ".gitignore"],
                    ["git", "rm", "-rf", ".scripts"],
                    ["git", "config", "user.email", "conda@conda.conda"],
                    ["git", "config", "user.name", "conda c. conda"],
                    ["git", "commit", "-m", "test commit"],
                ]
                for cmd in cmds:
                    subprocess.run(
                        cmd,
                        check=True,
                    )

            local_msg = rerender_feedstock(
                os.path.join(
                    tmpdir_local, "conda-forge-feedstock-check-solvable-feedstock"
                ),
                use_container=False,
            )

            assert local_msg is not None
            with pushd("conda-forge-feedstock-check-solvable-feedstock"):
                subprocess.run(
                    ["git", "commit", "-am", local_msg],
                    check=True,
                )

        # now run in container and make sure commit message is None
        msg = rerender_feedstock(
            os.path.join(
                tmpdir_local, "conda-forge-feedstock-check-solvable-feedstock"
            ),
            use_container=True,
        )

        assert msg is None


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_rerender_feedstock_containerized_permissions(use_containers):
    with tempfile.TemporaryDirectory() as tmpdir:
        with pushd(tmpdir):
            subprocess.run(
                [
                    "git",
                    "clone",
                    "https://github.com/conda-forge/conda-forge-feedstock-check-solvable-feedstock.git",
                ]
            )

            with pushd("conda-forge-feedstock-check-solvable-feedstock"):
                orig_perms_bl = os.stat("build-locally.py").st_mode
                print(
                    f"\n\ncloned permissions for build-locally.py: {orig_perms_bl:#o}\n\n"
                )
                orig_exec = get_user_execute_permissions(".")

            local_msg = rerender_feedstock(
                os.path.join(tmpdir, "conda-forge-feedstock-check-solvable-feedstock"),
                use_container=False,
            )

            if local_msg is not None:
                with pushd("conda-forge-feedstock-check-solvable-feedstock"):
                    cmds = [
                        ["git", "config", "user.email", "conda@conda.conda"],
                        ["git", "config", "user.name", "conda c. conda"],
                        ["git", "commit", "-am", local_msg],
                    ]
                    for cmd in cmds:
                        subprocess.run(cmd, check=True)

            # now change permissions
            with pushd("conda-forge-feedstock-check-solvable-feedstock"):
                orig_perms_bl = os.stat("build-locally.py").st_mode
                print(
                    f"\n\ninput permissions for build-locally.py: {orig_perms_bl:#o}\n\n"
                )
                local_rerend_exec = get_user_execute_permissions(".")

                cmds = [
                    ["chmod", "655", "build-locally.py"],
                    ["git", "add", "build-locally.py"],
                    ["git", "config", "user.email", "conda@conda.conda"],
                    ["git", "config", "user.name", "conda c. conda"],
                    ["git", "commit", "-m", "test commit for rerender"],
                ]
                for cmd in cmds:
                    subprocess.run(
                        cmd,
                        check=True,
                    )

            msg = rerender_feedstock(
                os.path.join(tmpdir, "conda-forge-feedstock-check-solvable-feedstock"),
                use_container=True,
            )
            assert msg is not None

            with pushd("conda-forge-feedstock-check-solvable-feedstock"):
                perms_bl = os.stat("build-locally.py").st_mode
                print(f"\n\nfinal permissions for build-locally.py: {perms_bl:#o}\n\n")
                cont_rerend_exec = get_user_execute_permissions(".")

            for item, perms in orig_exec.items():
                assert perms == local_rerend_exec.get(item, perms)
                assert perms == cont_rerend_exec.get(item, perms)


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_provide_source_code_containerized(use_containers):
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(tmpdir),
    ):
        subprocess.run(
            [
                "git",
                "clone",
                "https://github.com/conda-forge/conda-smithy-feedstock.git",
            ]
        )

        with provide_source_code_containerized(
            "conda-smithy-feedstock/recipe"
        ) as source_dir:
            assert os.path.exists(source_dir)
            assert os.path.isdir(source_dir)
            assert "conda_smithy" in os.listdir(source_dir)
            assert "pyproject.toml" in os.listdir(source_dir)


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_provide_source_code_containerized_patches(use_containers):
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(tmpdir),
    ):
        subprocess.run(
            [
                "git",
                "clone",
                "https://github.com/conda-forge/tiledb-feedstock.git",
            ]
        )
        with pushd("tiledb-feedstock"):
            subprocess.run(
                [
                    "git",
                    "checkout",
                    "2.23.x",
                ]
            )

        with provide_source_code_containerized("tiledb-feedstock/recipe") as source_dir:
            assert os.path.exists(source_dir)
            assert os.path.isdir(source_dir)
            assert "tiledb" in os.listdir(source_dir)
            assert "CMakeLists.txt" in os.listdir(source_dir)


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_is_recipe_solvable_containerized(use_containers):
    with tempfile.TemporaryDirectory() as tmpdir:
        with pushd(tmpdir):
            subprocess.run(
                [
                    "git",
                    "clone",
                    "https://github.com/conda-forge/conda-forge-feedstock-check-solvable-feedstock.git",
                ]
            )

        res_cont = is_recipe_solvable(
            os.path.join(tmpdir, "conda-forge-feedstock-check-solvable-feedstock"),
            use_container=True,
        )
        assert res_cont[0], res_cont

        res_local = is_recipe_solvable(
            os.path.join(tmpdir, "conda-forge-feedstock-check-solvable-feedstock"),
            use_container=False,
        )
        assert res_local[0], res_local

        assert res_cont == res_local


yaml_rebuild = MigrationYaml(yaml_contents="{}", name="hi", total_graph=TOTAL_GRAPH)
yaml_rebuild.cycles = []


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_migration_runner_run_migration_containerized_yaml_rebuild(tmpdir):
    fs_dir = os.path.join(tmpdir, "scipy-feedstock")
    rp_dir = os.path.join(fs_dir, "recipe")
    os.makedirs(rp_dir, exist_ok=True)
    with open(os.path.join(rp_dir, "meta.yaml"), "w") as f:
        f.write(sample_yaml_rebuild)

    with pushd(fs_dir):
        subprocess.run(["git", "init", "-b", "main"])
    # Load the meta.yaml (this is done in the graph)
    try:
        pmy = parse_meta_yaml(sample_yaml_rebuild)
    except Exception:
        pmy = {}
    if pmy:
        pmy["version"] = pmy["package"]["version"]
        pmy["req"] = set()
        for k in ["build", "host", "run"]:
            pmy["req"] |= set(pmy.get("requirements", {}).get(k, set()))
        try:
            pmy["meta_yaml"] = parse_meta_yaml(sample_yaml_rebuild)
        except Exception:
            pmy["meta_yaml"] = {}
    pmy["raw_meta_yaml"] = sample_yaml_rebuild

    migration_data = run_migration_containerized(
        migrator=yaml_rebuild,
        feedstock_dir=fs_dir,
        feedstock_name="scipy",
        node_attrs=pmy,
        default_branch="main",
    )

    pprint.pprint(migration_data)

    assert migration_data["migrate_return_value"] == {
        "migrator_name": yaml_rebuild.__class__.__name__,
        "migrator_version": yaml_rebuild.migrator_version,
        "name": "hi",
        "bot_rerun": False,
    }
    assert migration_data["commit_message"] == "Rebuild for hi"
    assert migration_data["pr_title"] == "Rebuild for hi"
    assert migration_data["pr_body"].startswith(
        "This PR has been triggered in an effort to update "
        "[**hi**](https://conda-forge.org/status/migration/?name=hi)."
    )

    with open(os.path.join(rp_dir, "meta.yaml")) as f:
        actual_output = f.read()
    assert actual_output == updated_yaml_rebuild
    assert os.path.exists(os.path.join(fs_dir, ".ci_support/migrations/hi.yaml"))
    with open(os.path.join(fs_dir, ".ci_support/migrations/hi.yaml")) as f:
        saved_migration = f.read()
    assert saved_migration == yaml_rebuild.yaml_contents


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
@pytest.mark.parametrize(
    "case,new_ver",
    [
        ("sha1", "5.0.1"),
    ],
)
def test_migration_runner_run_migration_containerized_version(
    case, new_ver, tmpdir, caplog
):
    caplog.set_level(
        logging.DEBUG,
        logger="conda_forge_tick.migrators.version",
    )

    with open(os.path.join(YAML_PATH, "version_%s.yaml" % case)) as fp:
        inp = fp.read()

    with open(os.path.join(YAML_PATH, "version_%s_correct.yaml" % case)) as fp:
        output = fp.read()

    kwargs = {}
    if case == "sha1":
        kwargs["hash_type"] = "sha1"

    m = VERSION
    mr_out = {
        "migrator_name": Version.name,
        "migrator_version": Version.migrator_version,
        "version": new_ver,
        "bot_rerun": False,
    }

    # Load the meta.yaml (this is done in the graph)
    try:
        name = parse_meta_yaml(inp)["package"]["name"]
    except Exception:
        name = "blah"

    fs_dir = os.path.join(tmpdir, f"{name}-feedstock")
    os.makedirs(os.path.join(fs_dir, "recipe"), exist_ok=True)

    with open(os.path.join(tmpdir, fs_dir, "recipe", "meta.yaml"), "w") as f:
        f.write(inp)

    pmy = populate_feedstock_attributes(name, {}, inp, None, "{}")

    # these are here for legacy migrators
    pmy["version"] = pmy["meta_yaml"]["package"]["version"]
    pmy["req"] = set()
    for k in ["build", "host", "run"]:
        req = pmy["meta_yaml"].get("requirements", {}) or {}
        _set = req.get(k) or set()
        pmy["req"] |= set(_set)
    pmy["raw_meta_yaml"] = inp
    pmy.update(kwargs)
    pmy["version_pr_info"] = {"new_version": new_ver}

    data = run_migration_containerized(
        migrator=m,
        feedstock_dir=fs_dir,
        feedstock_name=name,
        node_attrs=pmy,
        default_branch="main",
        **kwargs,
    )

    assert mr_out == data["migrate_return_value"]

    pmy["pr_info"] = {}
    pmy["pr_info"].update(PRed=[frozen_to_json_friendly(data["migrate_return_value"])])
    with open(os.path.join(tmpdir, fs_dir, "recipe", "meta.yaml")) as f:
        actual_output = f.read()
    assert actual_output == output
    assert m.filter(pmy) is True


@pytest.mark.skipif(
    not (HAVE_CONTAINERS and HAVE_TEST_IMAGE), reason="containers not available"
)
def test_container_tasks_update_version_feedstock_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        fs_dir = os.path.join(tmpdir, "mpich-feedstock")
        rp_dir = os.path.join(fs_dir, "recipe")
        os.makedirs(rp_dir, exist_ok=True)
        with open(os.path.join(rp_dir, "meta.yaml"), "w") as f:
            with open(os.path.join(YAML_PATH, "version_mpich.yaml")) as fp:
                f.write(fp.read())

        updated, errors = update_version_feedstock_dir(
            fs_dir, "4.1.1", use_container=True
        )
        assert updated
        assert not errors

        with open(os.path.join(rp_dir, "meta.yaml")) as f:
            actual_output = f.read()

        with open(os.path.join(YAML_PATH, "version_mpich_correct.yaml")) as fp:
            output = fp.read()

        assert actual_output == output


def test_container_tasks_provide_source_code_local(use_containers):
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        pushd(tmpdir),
    ):
        subprocess.run(
            [
                "git",
                "clone",
                "https://github.com/conda-forge/conda-smithy-feedstock.git",
            ]
        )

        with provide_source_code_local("conda-smithy-feedstock/recipe") as source_dir:
            assert os.path.exists(source_dir)
            assert os.path.isdir(source_dir)
            assert "pyproject.toml" in os.listdir(source_dir)
