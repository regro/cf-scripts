import copy
import json
import os
import subprocess

import conda_smithy

from conda_forge_tick.feedstock_parser import load_feedstock_containerized
from conda_forge_tick.lazy_json_backends import (
    LazyJson,
    dumps,
    lazy_json_override_backends,
)
from conda_forge_tick.update_upstream_versions import (
    all_version_sources,
    get_latest_version_containerized,
)
from conda_forge_tick.utils import get_default_container_name


def test_container_tasks_get_latest_version(monkeypatch):
    if "CI" not in os.environ:
        monkeypatch.setenv("CI", "true", prepend=False)

    res = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-t",
            f"{get_default_container_name()}",
            "python",
            "/opt/autotick-bot/docker/run_bot_task.py",
            "get-latest-version",
            "--existing-feedstock-node-attrs=conda-smithy",
        ],
        capture_output=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout.decode("utf-8"))
    assert data["new_version"] == conda_smithy.__version__


def test_container_tasks_get_latest_version_json(monkeypatch):
    if "CI" not in os.environ:
        monkeypatch.setenv("CI", "true", prepend=False)

    with lazy_json_override_backends(["github"], use_file_cache=False):
        with LazyJson("node_attrs/conda-smithy.json") as lzj:
            existing_feedstock_node_attrs = dumps(lzj.data)

    res = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-t",
            f"{get_default_container_name()}",
            "python",
            "/opt/autotick-bot/docker/run_bot_task.py",
            "get-latest-version",
            "--existing-feedstock-node-attrs",
            existing_feedstock_node_attrs,
        ],
        capture_output=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout.decode("utf-8"))
    assert data["new_version"] == conda_smithy.__version__


def test_get_latest_version_containerized(monkeypatch):
    # if the user doesn't set CI, assume we are in CI
    if "CI" not in os.environ:
        monkeypatch.setenv("CI", "true", prepend=False)
    with lazy_json_override_backends(["github"], use_file_cache=False):
        with LazyJson("node_attrs/conda-smithy.json") as lzj:
            attrs = copy.deepcopy(lzj.data)

    data = get_latest_version_containerized(
        "conda-smithy", attrs, all_version_sources()
    )
    assert data["new_version"] == conda_smithy.__version__


def test_container_tasks_parse_feedstock(monkeypatch):
    if "CI" not in os.environ:
        monkeypatch.setenv("CI", "true", prepend=False)

    res = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-t",
            f"{get_default_container_name()}",
            "python",
            "/opt/autotick-bot/docker/run_bot_task.py",
            "parse-feedstock",
            "--existing-feedstock-node-attrs=conda-smithy",
        ],
        capture_output=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout.decode("utf-8"))
    with lazy_json_override_backends(["github"], use_file_cache=False), LazyJson(
        "node_attrs/conda-smithy.json"
    ) as lzj:
        attrs = copy.deepcopy(lzj.data)

    assert data["feedstock_name"] == attrs["feedstock_name"]
    assert not data["parsing_error"]
    assert data["raw_meta_yaml"] == attrs["raw_meta_yaml"]


def test_container_tasks_parse_feedstock_json(monkeypatch):
    if "CI" not in os.environ:
        monkeypatch.setenv("CI", "true", prepend=False)

    with lazy_json_override_backends(["github"], use_file_cache=False):
        with LazyJson("node_attrs/conda-smithy.json") as lzj:
            attrs = copy.deepcopy(lzj.data)
            existing_feedstock_node_attrs = dumps(lzj.data)

    res = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-t",
            f"{get_default_container_name()}",
            "python",
            "/opt/autotick-bot/docker/run_bot_task.py",
            "parse-feedstock",
            "--existing-feedstock-node-attrs",
            existing_feedstock_node_attrs,
        ],
        capture_output=True,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout.decode("utf-8"))
    assert data["feedstock_name"] == attrs["feedstock_name"]
    assert not data["parsing_error"]
    assert data["raw_meta_yaml"] == attrs["raw_meta_yaml"]


def test_load_feedstock_containerized(monkeypatch):
    # if the user doesn't set CI, assume we are in CI
    if "CI" not in os.environ:
        monkeypatch.setenv("CI", "true", prepend=False)
    with lazy_json_override_backends(["github"], use_file_cache=False):
        with LazyJson("node_attrs/conda-smithy.json") as lzj:
            attrs = copy.deepcopy(lzj.data)

    data = load_feedstock_containerized("conda-smithy", attrs)
    assert data["feedstock_name"] == attrs["feedstock_name"]
    assert not data["parsing_error"]
    assert data["raw_meta_yaml"] == attrs["raw_meta_yaml"]
