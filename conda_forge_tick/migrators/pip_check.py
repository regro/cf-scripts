import re
import typing
from typing import Any
from ruamel.yaml import YAML
import ruamel.yaml
import io

from conda_forge_tick.xonsh_utils import indir
from conda_forge_tick.migrators.core import MiniMigrator

if typing.TYPE_CHECKING:
    from ..migrators_types import AttrsTypedDict

# matches lines like 'key: val  # [blah or blad]'
# giving back key, val, "blah or blad" in the groups
SELECTOR_RE = re.compile(r'^(\s*)(\S*):\s*(\S*)\s*#\s*\[(.*)\]')


def _munge_key(key, selector):
    return (
        key
        + '__conda-selector_'
        + (
            selector
            .replace(' ', '_spc_')
            .replace('(', '_lparens_')
            .replace(')', '_rparens_')
            .replace('<=', '_le_')
            .replace('>=', '_ge_')
            .replace('<', '_lt_')
            .replace('>', '_gt_')
            .replace('==', '_eq2_')
            .replace('=', '_eq1_')
            .replace('&&', '_andsym2_')
            .replace('||', '_orsym2_')
            .replace('&', '_andsym1_')
            .replace('|', '_orsym1_')
        )
    )


def _round_trip_value(val):
    yaml = YAML(typ='jinja2')
    s = io.StringIO()
    yaml.dump({'key': yaml.load(val)}, s)
    s.seek(0)
    return s.read().split(':')[1].strip()


def _munge_line(line, mapping, groups):
    m = SELECTOR_RE.match(line)
    if m:
        spc, key, val, selector = m.group(1, 2, 3, 4)
        new_key = _munge_key(key, selector)
        val = _round_trip_value(val)
        groups[new_key] = (spc, key, val, selector)
        mapping[(spc, new_key, val, selector)] = line
        return line.replace(key + ':', new_key + ':')
    else:
        return line


def _unmunge_line(line, mapping):
    m = SELECTOR_RE.match(line)
    if m:
        tup = m.group(1, 2, 3, 4)
        return mapping.get(tup, line)
    else:
        return line


def _has_python_in_host(host):
    host_set = {r.split(" ")[0] for r in host}
    return bool(host_set & set(["python"]))


def _gen_keys_selector(meta, base):
    for key in meta.keys():
        if key == base or key.startswith(base + '__conda-selector'):
            yield key, meta[key]


def _has_key_selector(meta, base):
    return len([val for val in _gen_keys_selector(meta, base)]) > 0


def _adjust_test_dict(meta, key, mapping, groups, parent_group=None):
    if _has_key_selector(meta[key], 'requires'):
        for _key, val in _gen_keys_selector(meta[key], 'requires'):
            val.append('pip')
            if _key in groups:
                val.yaml_add_eol_comment(
                    '# [%s]' % groups[_key][3],
                    len(val) - 1,
                    column=2,
                )
    elif _has_key_selector(meta[key], 'requirements'):
        for _key, val in _gen_keys_selector(meta[key], 'requirements'):
            val.append('pip')
            if _key in groups:
                val.yaml_add_eol_comment(
                    '# [%s]' % groups[_key][3],
                    len(val) - 1,
                    column=80,
                )
    else:
        new_seq = ruamel.yaml.comments.CommentedSeq()
        new_seq.append('pip')
        meta[key]['requires'] = new_seq
        if parent_group is not None:
            new_seq.yaml_add_eol_comment(
                '# [%s]' % parent_group[3],
                0,
                column=80,
            )
            meta[key].yaml_add_eol_comment(
                '# [%s]' % parent_group[3],
                'requires',
                column=80,
            )

    if _has_key_selector(meta[key], 'commands'):
        for _key, val in _gen_keys_selector(meta[key], 'commands'):
            val.append('python -m pip check')
            if _key in groups:
                val.yaml_add_eol_comment(
                    '# [%s]' % groups[_key][3],
                    len(val) - 1,
                    column=80,
                )
    else:
        new_seq = ruamel.yaml.comments.CommentedSeq()
        new_seq.append('python -m pip check')
        meta[key]['commands'] = new_seq
        if parent_group is not None:
            new_seq.yaml_add_eol_comment(
                '# [%s]' % parent_group[3],
                0,
                column=80,
            )
            meta[key].yaml_add_eol_comment(
                '# [%s]' % parent_group[3],
                'commands',
                column=80,
            )


class PipCheckMigrator(MiniMigrator):
    def filter(self, attrs: "AttrsTypedDict", not_bad_str_start: str = "") -> bool:
        """run pip check if we see python in any host sections"""
        build_host = (
            attrs['requirements'].get('host', set()) or
            attrs['requirements'].get('build', set()) or
            set()
        )
        return "python" not in build_host

    def migrate(self, recipe_dir: str, attrs: "AttrsTypedDict", **kwargs: Any) -> None:
        with indir(recipe_dir):
            mapping = {}
            groups = {}
            with open('meta.yaml', 'r') as fp:
                lines = []
                for line in fp.readlines():
                    lines.append(_munge_line(line, mapping, groups))

            yaml = YAML(typ='jinja2')
            yaml.indent(mapping=2, sequence=4, offset=2)
            yaml.width = 120

            meta = yaml.load(''.join(lines))

            if not _has_key_selector(meta, 'outputs'):
                for key, _ in _gen_keys_selector(meta, 'test'):
                    _adjust_test_dict(
                        meta,
                        key,
                        mapping,
                        groups,
                        parent_group=groups.get(key, None),
                    )
            else:
                # do top level
                has_python = False
                for _, val in _gen_keys_selector(meta, 'requirements'):
                    for _key, reqs in _gen_keys_selector(val, 'host'):
                        has_python |= _has_python_in_host(reqs)

                has_test_imports = False
                for _, val in _gen_keys_selector(meta, 'test'):
                    has_test_imports |= _has_key_selector(val, 'imports')

                if has_python or has_test_imports:
                    for key, _ in _gen_keys_selector(meta, 'test'):
                        _adjust_test_dict(
                            meta,
                            key,
                            mapping,
                            groups,
                            parent_group=groups.get(key, None),
                        )

                # now outputs
                for _, outputs in _gen_keys_selector(meta, 'outputs'):
                    for output in outputs:
                        has_python = False
                        for _, val in _gen_keys_selector(output, 'requirements'):
                            for _key, reqs in _gen_keys_selector(val, 'host'):
                                has_python |= _has_python_in_host(reqs)

                        if has_python:
                            for key, _ in _gen_keys_selector(output, 'test'):
                                _adjust_test_dict(
                                    output,
                                    key,
                                    mapping,
                                    groups,
                                    parent_group=groups.get(key, None),
                                )

            with open('meta.yaml', 'w') as fp:
                yaml.dump(meta, fp)

            # now undo mapping
            with open('meta.yaml', 'r') as fp:
                lines = []
                for line in fp.readlines():
                    lines.append(_unmunge_line(line, mapping))

            with open('meta.yaml', 'w') as fp:
                for line in lines:
                    fp.write(line)
