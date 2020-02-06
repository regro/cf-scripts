import typing
from typing import Any
from ruamel.yaml import YAML

from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.migrators.core import MiniMigrator

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict


def _has_python_in_host(host):
    host_set = {r.split(" ")[0] for r in host}
    return bool(host_set & set(["python"]))


def _adjust_test_dict(test):
    if 'requires' in test:
        test['requires'].append('pip')
    else:
        test['requires'] = ['pip']

    if 'commands' in test:
        test['commands'].append('{{ PYTHON }} -m pip check')
    else:
        test['commands'] = ['{{ PYTHON }} -m pip check']


class PipCheckMigrator(MiniMigrator):
    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """run pip check if we see python in any host sections"""
        filter_top_level = "python" not in attrs['requirements'].get('host', set())
        # FIXME - check outputs too
        return filter_top_level

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            yaml = YAML(typ='jinja2')
            yaml.indent(mapping=2, sequence=4, offset=2)
            yaml.allow_duplicate_keys = True

            with open('meta.yaml', 'r') as fp:
                meta = yaml.load(fp)

            if "outputs" not in meta:
                _adjust_test_dict(meta['test'])
            else:
                host_req = meta.get('requirements', {}).get('host', [])
                has_python = _has_python_in_host(host_req)
                if 'test' in meta and (has_python or 'imports' in meta['test']):
                    _adjust_test_dict(meta['test'])

                for output in meta['outputs']:
                    host_req = output.get('requirements', {}).get('host', [])
                    has_python = _has_python_in_host(host_req)
                    if has_python and 'test' in output:
                        _adjust_test_dict(output['test'])

            with open('meta.yaml', 'w') as fp:
                yaml.dump(meta, fp)
