"""
Similar to test-status, but for reports
"""
from typing import Any

from conda_forge_tick.migrators import GraphMigrator, Version
from conda_forge_tick.auto_tick import initialize_migrators
from conda_forge_tick.status_report import (
    graph_migrator_status,
    write_version_migrator_status,
)
import yaml


def main(args: Any = None) -> None:
    mctx, *_, migrators = initialize_migrators()

    for migrator in migrators:
        if isinstance(migrator, GraphMigrator):
            migrator_name = migrator.__class__.__name__.lower()
            print(migrator_name)
            print("=" * len(migrator_name))
            status, build_order, gv = graph_migrator_status(migrator, mctx.graph)
            o = yaml.safe_dump(status, default_flow_style=False)
            print(o)
            print("\n\n")
        elif isinstance(migrator, Version):
            write_version_migrator_status(migrator, mctx)


if __name__ == "__main__":
    main()
