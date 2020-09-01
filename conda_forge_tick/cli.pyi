import typing

class CLIArgs(typing.NamedTuple):
    dry_run: bool
    debug: bool
    run: typing.Any
    cf_graph: str
