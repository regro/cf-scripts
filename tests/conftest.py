import json
import os
import shutil
import subprocess
import tempfile
from types import TracebackType
from typing import Self

import networkx as nx
import pytest

from conda_forge_tick import global_sensitive_env
from conda_forge_tick.lazy_json_backends import LazyJson

_HAVE_CONTAINERS = (
    shutil.which("docker") is not None
    and subprocess.run(["docker", "--version"], capture_output=True).returncode == 0
)

if _HAVE_CONTAINERS:
    _HAVE_TEST_IMAGE = False
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
                _HAVE_TEST_IMAGE = True
                break
    except subprocess.CalledProcessError as e:
        print(
            f"Could not list local docker images due "
            f"to error {e}. Skipping container tests!"
        )

HAVE_CONTAINERS_AND_TEST_IMAGE = _HAVE_CONTAINERS and _HAVE_TEST_IMAGE


@pytest.fixture
def env_setup():
    if "TEST_BOT_TOKEN_VAL" not in os.environ:
        old_pwd = os.environ.pop("BOT_TOKEN", None)
        os.environ["BOT_TOKEN"] = "unpassword"
        global_sensitive_env.hide_env_vars()

    old_pwd2 = os.environ.pop("pwd", None)
    os.environ["pwd"] = "pwd"

    yield

    if "TEST_BOT_TOKEN_VAL" not in os.environ:
        global_sensitive_env.reveal_env_vars()
        if old_pwd:
            os.environ["BOT_TOKEN"] = old_pwd

    if old_pwd2:
        os.environ["pwd"] = old_pwd2


@pytest.fixture(autouse=True, scope="session")
def set_cf_feedstock_ops_container_tag_to_test():
    old_cftct = os.environ.get("CF_FEEDSTOCK_OPS_CONTAINER_TAG")
    if old_cftct is None:
        os.environ["CF_FEEDSTOCK_OPS_CONTAINER_TAG"] = "test"

    yield

    if old_cftct is None:
        del os.environ["CF_FEEDSTOCK_OPS_CONTAINER_TAG"]
    else:
        os.environ["CF_FEEDSTOCK_OPS_CONTAINER_TAG"] = old_cftct


@pytest.fixture(autouse=True, scope="session")
def set_cf_feedstock_ops_container_name_to_local():
    old_cftcn = os.environ.get("CF_FEEDSTOCK_OPS_CONTAINER_NAME")
    if old_cftcn is None:
        os.environ["CF_FEEDSTOCK_OPS_CONTAINER_NAME"] = "conda-forge-tick"

    yield

    if old_cftcn is None:
        del os.environ["CF_FEEDSTOCK_OPS_CONTAINER_NAME"]
    else:
        os.environ["CF_FEEDSTOCK_OPS_CONTAINER_NAME"] = old_cftcn


@pytest.fixture(autouse=True, scope="session")
def turn_off_containers_by_default():
    old_in_container = os.environ.get("CF_FEEDSTOCK_OPS_IN_CONTAINER")

    # tell the code we are in a container so that it
    # doesn't try to run docker commands
    os.environ["CF_FEEDSTOCK_OPS_IN_CONTAINER"] = "true"

    yield

    if old_in_container is None:
        os.environ.pop("CF_FEEDSTOCK_OPS_IN_CONTAINER", None)
    else:
        os.environ["CF_FEEDSTOCK_OPS_IN_CONTAINER"] = old_in_container


@pytest.fixture
def use_containers():
    old_in_container = os.environ.get("CF_FEEDSTOCK_OPS_IN_CONTAINER")

    os.environ["CF_FEEDSTOCK_OPS_IN_CONTAINER"] = "false"

    yield

    if old_in_container is None:
        os.environ.pop("CF_FEEDSTOCK_OPS_IN_CONTAINER", None)
    else:
        os.environ["CF_FEEDSTOCK_OPS_IN_CONTAINER"] = old_in_container


class FakeLazyJson(dict):
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    @property
    def data(self):
        return self


@pytest.fixture
def test_graph():
    with tempfile.TemporaryDirectory() as tmpdir:
        gx = nx.DiGraph()
        lzj = LazyJson(os.path.join(tmpdir, "conda.json"))
        with lzj as attrs:
            attrs.update({"reqs": ["python"]})
        gx.add_node("conda", payload=lzj)
        gx.graph["outputs_lut"] = {}

        yield gx


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "mongodb: mark tests that run with mongodb",
    )


@pytest.fixture
def temporary_environment():
    try:
        old_env = os.environ.copy()
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_env)
