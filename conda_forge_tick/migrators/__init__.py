# flake8: noqa
from .core import (
    Migrator,
    GraphMigrator,
    MiniMigrator,
    Replacement,
)
from .conda_forge_yaml_cleanup import CondaForgeYAMLCleanup
from .mpi_pin_run_as_build import MPIPinRunAsBuildCleanup
from .migration_yaml import MigrationYaml, MigrationYamlCreator, merge_migrator_cbc
from .arch import ArchRebuild, OSXArm
from .pip_check import PipCheckMigrator
from .matplotlib_base import MatplotlibBase
from .extra_jinj2a_keys_cleanup import ExtraJinja2KeysCleanup
from .version import Version
from .use_pip import PipMigrator
from .jinja2_vars_cleanup import Jinja2VarsCleanup
from .license import LicenseMigrator
from .cross_compile import (
    UpdateConfigSubGuessMigrator,
    UpdateCMakeArgsMigrator,
    GuardTestingMigrator,
    CrossPythonMigrator,
    CrossRBaseMigrator,
    Build2HostMigrator,
    NoCondaInspectMigrator,
    CrossCompilationForARMAndPower,
)
from .duplicate_lines import DuplicateLinesCleanup
from .cos7 import Cos7Config
from .pip_wheel_dep import PipWheelMigrator
from .broken_rebuild import RebuildBroken
from .dep_updates import DependencyUpdateMigrator
