from .pypi_name_mapping import main as main_pypi_name_mapping


def main(args):
    """Run all the mapping updaters"""
    main_pypi_name_mapping(args)
