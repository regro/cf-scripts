import hashlib
import inspect

import conda_forge_tick.migrators
from conda_forge_tick.lazy_json_backends import dumps


def test_migrator_to_json_dep_update_minimigrator():
    python_nodes = ["blah"]
    migrator = conda_forge_tick.migrators.DependencyUpdateMigrator(python_nodes)
    assert migrator._init_args == [python_nodes]
    assert migrator._init_kwargs == {}
    data = migrator.to_lazy_json_data()
    dumps(data)
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

    migrator2 = conda_forge_tick.migrators.MiniMigrator.from_lazy_json_data(data)
    assert migrator2._init_args == [python_nodes]
    assert migrator2._init_kwargs == {}
    assert isinstance(migrator2, conda_forge_tick.migrators.DependencyUpdateMigrator)
    assert migrator2.to_lazy_json_data() == data


def test_migrator_to_json_minimigrators():
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
            dumps(data)
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
                "args": [],
                "kwargs": {},
                "name": f"{migrator_name}_h{hsh}",
                "class": migrator_name,
            }

            migrator2 = conda_forge_tick.migrators.MiniMigrator.from_lazy_json_data(
                data
            )
            assert migrator2._init_args == []
            assert migrator2._init_kwargs == {}
            assert isinstance(migrator2, migrator.__class__)
            assert migrator2.to_lazy_json_data() == data


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
    dumps(data)
    assert data["__migrator__"] is True
    assert data["class"] == "Version"

    migrator2 = conda_forge_tick.migrators.Migrator.from_lazy_json_data(data)
    assert isinstance(migrator2, conda_forge_tick.migrators.Version)
    assert migrator2.to_lazy_json_data() == data
