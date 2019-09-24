"""
Similar to test-status, but for reports
"""
from conda_forge_tick.utils import setup_logger
from .migrators import Rebuild
from .auto_tick import initialize_migrators, migrator_status
import os
import yaml


def main(args=None):
    gx, *_, migrators = initialize_migrators(do_rebuild=True)

    for migrator in migrators:
        if isinstance(migrator, Rebuild):
            migrator_name = migrator.__class__.__name__.lower()
            print(migrator_name)
            print('=' * len(migrator_name))
            status, build_order, gv = migrator_status(migrator, gx)
            o = yaml.safe_dump(status, default_flow_style=False)
            print(o)
            print('\n\n')

if __name__ == '__main__':
    main()