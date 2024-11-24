import hashlib
import inspect
import pprint

import networkx as nx

import conda_forge_tick.migrators
from conda_forge_tick.lazy_json_backends import dumps, loads
from conda_forge_tick.migrators import make_from_lazy_json_data


def test_migrator_to_json_dep_update_minimigrator():
    python_nodes = ["blah"]
    migrator = conda_forge_tick.migrators.DependencyUpdateMigrator(python_nodes)
    assert migrator._init_args == [python_nodes]
    assert migrator._init_kwargs == {}
    data = migrator.to_lazy_json_data()
    pprint.pprint(data)
    lzj_data = dumps(data)
    hsh = hashlib.sha1(
        dumps(
            {
                "class": data["class"],
                "args": data["args"],
                "kwargs": data["kwargs"],
            }
        ).encode("utf-8")
    ).hexdigest()

    assert data == {
        "__mini_migrator__": True,
        "args": [python_nodes],
        "kwargs": {},
        "name": f"DependencyUpdateMigrator_h{hsh}",
        "class": "DependencyUpdateMigrator",
    }

    migrator2 = make_from_lazy_json_data(loads(lzj_data))
    assert migrator2._init_args == [python_nodes]
    assert migrator2._init_kwargs == {}
    assert isinstance(migrator2, conda_forge_tick.migrators.DependencyUpdateMigrator)
    assert dumps(migrator2.to_lazy_json_data()) == lzj_data


def test_migrator_to_json_minimigrators_nodeps():
    possible_migrators = dir(conda_forge_tick.migrators)
    for migrator_name in possible_migrators:
        migrator = getattr(conda_forge_tick.migrators, migrator_name)
        if (
            inspect.isclass(migrator)
            and issubclass(migrator, conda_forge_tick.migrators.MiniMigrator)
            and migrator != conda_forge_tick.migrators.MiniMigrator
            and migrator != conda_forge_tick.migrators.DependencyUpdateMigrator
        ):
            migrator = migrator()
            data = migrator.to_lazy_json_data()
            pprint.pprint(data)
            lzj_data = dumps(data)
            assert data == {
                "__mini_migrator__": True,
                "args": [],
                "kwargs": {},
                "name": migrator_name,
                "class": migrator_name,
            }

            migrator2 = make_from_lazy_json_data(loads(lzj_data))
            assert migrator2._init_args == []
            assert migrator2._init_kwargs == {}
            assert isinstance(migrator2, migrator.__class__)
            assert dumps(migrator2.to_lazy_json_data()) == lzj_data


def test_migrator_to_json_version():
    migrator = conda_forge_tick.migrators.Version(
        set(),
        piggy_back_migrations=[
            conda_forge_tick.migrators.DependencyUpdateMigrator(["blah"]),
            conda_forge_tick.migrators.DependencyUpdateMigrator(["blah2"]),
            conda_forge_tick.migrators.LibboostMigrator(),
            conda_forge_tick.migrators.DuplicateLinesCleanup(),
        ],
    )
    data = migrator.to_lazy_json_data()
    pprint.pprint(data)

    lzj_data = dumps(data)
    print("lazy json data:\n", lzj_data)

    assert data["__migrator__"] is True
    assert data["class"] == "Version"

    migrator2 = make_from_lazy_json_data(loads(lzj_data))
    assert [pgm.__class__.__name__ for pgm in migrator2.piggy_back_migrations] == [
        pgm.__class__.__name__ for pgm in migrator.piggy_back_migrations
    ]
    assert isinstance(migrator2, conda_forge_tick.migrators.Version)
    assert dumps(migrator2.to_lazy_json_data()) == lzj_data


def test_migrator_to_json_migration_yaml_creator():
    gx = nx.DiGraph()
    gx.add_node("conda", reqs=["python"], payload={}, blah="foo")
    gx.graph["outputs_lut"] = {}

    pname = "boost"
    pin_ver = "1.99.0"
    curr_pin = "1.70.0"
    pin_spec = "x.x"

    migrator = conda_forge_tick.migrators.MigrationYamlCreator(
        pname,
        pin_ver,
        curr_pin,
        pin_spec,
        "hi",
        gx,
        gx,
        blah="foo",
    )
    data = migrator.to_lazy_json_data()
    pprint.pprint(data)
    assert data["kwargs"]["blah"] == "foo"

    lzj_data = dumps(data)
    print("lazy json data:\n", lzj_data)

    assert data["__migrator__"] is True
    assert data["class"] == "MigrationYamlCreator"
    assert data["name"] == pname + "_pinning"

    migrator2 = make_from_lazy_json_data(loads(lzj_data))
    assert [pgm.__class__.__name__ for pgm in migrator2.piggy_back_migrations] == [
        pgm.__class__.__name__ for pgm in migrator.piggy_back_migrations
    ]
    assert isinstance(migrator2, conda_forge_tick.migrators.MigrationYamlCreator)
    assert dumps(migrator2.to_lazy_json_data()) == lzj_data


def test_migrator_to_json_matplotlib_base():
    migrator = conda_forge_tick.migrators.MatplotlibBase(
        old_pkg="matplotlib",
        new_pkg="matplotlib-base",
        rationale=(
            "Unless you need `pyqt`, recipes should depend only on "
            "`matplotlib-base`."
        ),
        pr_limit=5,
    )
    data = migrator.to_lazy_json_data()
    pprint.pprint(data)
    lzj_data = dumps(data)
    print("lazy json data:\n", lzj_data)
    assert data["__migrator__"] is True
    assert data["class"] == "MatplotlibBase"
    assert data["name"] == "matplotlib-to-matplotlib-base"

    migrator2 = make_from_lazy_json_data(loads(lzj_data))
    assert [pgm.__class__.__name__ for pgm in migrator2.piggy_back_migrations] == [
        pgm.__class__.__name__ for pgm in migrator.piggy_back_migrations
    ]
    assert isinstance(migrator2, conda_forge_tick.migrators.MatplotlibBase)
    assert dumps(migrator2.to_lazy_json_data()) == lzj_data


def test_migrator_to_json_migration_yaml():
    migrator = conda_forge_tick.migrators.MigrationYaml(
        yaml_contents="hello world",
        name="hi",
        blah="foo",
    )

    data = migrator.to_lazy_json_data()
    pprint.pprint(data)
    assert data["kwargs"]["blah"] == "foo"
    lzj_data = dumps(data)
    print("lazy json data:\n", lzj_data)

    assert data["__migrator__"] is True
    assert data["class"] == "MigrationYaml"
    assert data["name"] == "hi"

    migrator2 = make_from_lazy_json_data(loads(lzj_data))
    assert [pgm.__class__.__name__ for pgm in migrator2.piggy_back_migrations] == [
        pgm.__class__.__name__ for pgm in migrator.piggy_back_migrations
    ]
    assert isinstance(migrator2, conda_forge_tick.migrators.MigrationYaml)
    assert dumps(migrator2.to_lazy_json_data()) == lzj_data


def test_migrator_to_json_rebuild():
    migrator = conda_forge_tick.migrators.Replacement(
        old_pkg="matplotlib",
        new_pkg="matplotlib-base",
        rationale=(
            "Unless you need `pyqt`, recipes should depend only on "
            "`matplotlib-base`."
        ),
        pr_limit=5,
    )

    data = migrator.to_lazy_json_data()
    pprint.pprint(data)
    lzj_data = dumps(data)
    print("lazy json data:\n", lzj_data)
    assert data["__migrator__"] is True
    assert data["class"] == "Replacement"
    assert data["name"] == "matplotlib-to-matplotlib-base"

    migrator2 = make_from_lazy_json_data(loads(lzj_data))
    assert [pgm.__class__.__name__ for pgm in migrator2.piggy_back_migrations] == [
        pgm.__class__.__name__ for pgm in migrator.piggy_back_migrations
    ]
    assert isinstance(migrator2, conda_forge_tick.migrators.Replacement)
    assert dumps(migrator2.to_lazy_json_data()) == lzj_data


def test_migrator_to_json_arch():
    gx = nx.DiGraph()
    gx.add_node("conda", reqs=["python"], payload={}, blah="foo")

    migrator = conda_forge_tick.migrators.ArchRebuild(
        target_packages=["python"],
        graph=gx,
        pr_limit=5,
        name="aarch64 and ppc64le addition",
    )

    data = migrator.to_lazy_json_data()
    pprint.pprint(data)
    lzj_data = dumps(data)
    print("lazy json data:\n", lzj_data)
    assert data["__migrator__"] is True
    assert data["class"] == "ArchRebuild"
    assert data["name"] == "aarch64_and_ppc64le_addition"

    migrator2 = make_from_lazy_json_data(loads(lzj_data))
    assert [pgm.__class__.__name__ for pgm in migrator2.piggy_back_migrations] == [
        pgm.__class__.__name__ for pgm in migrator.piggy_back_migrations
    ]
    assert isinstance(migrator2, conda_forge_tick.migrators.ArchRebuild)
    assert dumps(migrator2.to_lazy_json_data()) == lzj_data


def test_migrator_to_json_osx_arm():
    gx = nx.DiGraph()
    gx.add_node("conda", reqs=["python"], payload={}, blah="foo")

    migrator = conda_forge_tick.migrators.OSXArm(
        target_packages=["python"],
        graph=gx,
        pr_limit=5,
        name="arm osx addition",
    )

    data = migrator.to_lazy_json_data()
    pprint.pprint(data)
    lzj_data = dumps(data)
    print("lazy json data:\n", lzj_data)
    assert data["__migrator__"] is True
    assert data["class"] == "OSXArm"
    assert data["name"] == "arm_osx_addition"

    migrator2 = make_from_lazy_json_data(loads(lzj_data))
    assert [pgm.__class__.__name__ for pgm in migrator2.piggy_back_migrations] == [
        pgm.__class__.__name__ for pgm in migrator.piggy_back_migrations
    ]
    assert isinstance(migrator2, conda_forge_tick.migrators.OSXArm)
    assert dumps(migrator2.to_lazy_json_data()) == lzj_data
