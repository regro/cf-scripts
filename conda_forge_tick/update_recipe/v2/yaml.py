import io
from pathlib import Path

from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 4096
yaml.indent(mapping=2, sequence=4, offset=2)


def _load_yaml(file: Path) -> dict:
    """Load a YAML file."""
    with file.open("r") as f:
        return yaml.load(f)


def _dump_yaml_to_str(data: dict) -> str:
    """Dump a dictionary to a YAML string."""
    with io.StringIO() as f:
        yaml.dump(data, f)
        return f.getvalue()
