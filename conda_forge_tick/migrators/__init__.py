# flake8: noqa
from .arch import ArchRebuild, OSXArm
from .broken_rebuild import RebuildBroken
from .conda_forge_yaml_cleanup import CondaForgeYAMLCleanup
from .core import (
    GraphMigrator,
    Migrator,
    MiniMigrator,
    make_from_lazy_json_data,
    skip_migrator_due_to_schema,
)
from .cos7 import Cos7Config
from .cross_compile import (
    Build2HostMigrator,
    CrossCompilationForARMAndPower,
    CrossPythonMigrator,
    CrossRBaseMigrator,
    GuardTestingMigrator,
    NoCondaInspectMigrator,
    UpdateCMakeArgsMigrator,
    UpdateConfigSubGuessMigrator,
)
from .cstdlib import StdlibMigrator
from .dep_updates import DependencyUpdateMigrator
from .duplicate_lines import DuplicateLinesCleanup
from .extra_jinj2a_keys_cleanup import ExtraJinja2KeysCleanup
from .flang import FlangMigrator
from .jinja2_vars_cleanup import Jinja2VarsCleanup
from .jpegturbo import JpegTurboMigrator
from .libboost import LibboostMigrator
from .license import LicenseMigrator
from .matplotlib_base import MatplotlibBase
from .migration_yaml import MigrationYaml, MigrationYamlCreator, merge_migrator_cbc
from .mpi_pin_run_as_build import MPIPinRunAsBuildCleanup
from .numpy2 import Numpy2Migrator
from .pip_check import PipCheckMigrator
from .pip_wheel_dep import PipWheelMigrator
from .pypi_org import PyPIOrgMigrator
from .qt_to_qt_main import QtQtMainMigrator
from .r_ucrt import RUCRTCleanup
from .replacement import Replacement
from .use_pip import PipMigrator
from .version import Version
from .xz_to_liblzma_devel import XzLibLzmaDevelMigrator
from .noarch_python_min import NoarchPythonMinMigrator
from .nvtools import AddNVIDIATools
from .round_trip import YAMLRoundTrip
from .staticlib import StaticLibMigrator
