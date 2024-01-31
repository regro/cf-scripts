from .cli_context import CliContext
from .pypi_name_mapping import main as main_pypi_name_mapping


def main(_: CliContext = CliContext()):
    """Run all the mapping updaters"""
    main_pypi_name_mapping()
