from dataclasses import dataclass


@dataclass
class CliContext:
    debug: bool = True
    dry_run: bool = True
