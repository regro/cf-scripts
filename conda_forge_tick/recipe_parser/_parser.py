import jinja2
import re
import io
import collections.abc
import json
from typing import Union, List, Any

from ruamel.yaml import YAML

CONDA_SELECTOR = '__###conda-selector###__'

# this regex pulls out lines like
#  '   name: val # [sel]'
# to groups ('   ', 'name', 'val ', 'sel')
SPC_KEY_VAL_SELECTOR_RE = re.compile(r'^(\s*)(.*):(.*)#\s*\[(.*)\]')

# this regex pulls out lines like
#  '   name__###conda-selector###__py3k and blah: val # comment'
# to groups ('   ', 'name', 'py3k and blah', ' val # comment')
MUNGED_LINE_RE = re.compile(r'^(\s*)(\S*)' + CONDA_SELECTOR + r'(.*):(.*)')

# this regex matches any line with a selector
SELECTOR_RE = re.compile(r'^.*#\s*\[(.*)\]')

# yaml parser that is jinja2 aware
YAML_JINJA2 = YAML(typ='jinja2')
YAML_JINJA2.indent(mapping=2, sequence=4, offset=2)
YAML_JINJA2.width = 100


def _config_has_key_with_selectors(cfg: dict, key: str):
    for _key in cfg:
        if _key == key or _key.startswith(key + CONDA_SELECTOR):
            return True
    return False


def _parse_jinja2_variables(meta_yaml: str) -> dict:
    """Parse all assignements of jinja2 variables in a recipe.

    For example, the following file

        ```
        {% set var1 = 'blah' %}
        {% set var2 = 4 %}  # [py2k and win]
        ```

    produces a dictionary

        ```
        'var1': 'blah'
        'var2__###conda-selector###__py2k and win': 4
        ```

    Parameters
    ----------
    meta_yaml : str
        The recipe as a string

    Returns
    -------
    jinja2_vars : dict
        A dictionary mapping the jinja2 variables to their values.
        Note that if a selector has been applied in the recipe, the
        name of the variable will be `<name>__###conda-selector###__<selector>`.
    """
    env = jinja2.Environment()
    parsed_content = env.parse(meta_yaml)
    all_nodes = list(parsed_content.iter_child_nodes())

    jinja2_vals = {}
    for i, n in enumerate(all_nodes):
        if isinstance(n, jinja2.nodes.Assign):
            if not hasattr(n.node, "value"):
                continue

            if _config_has_key_with_selectors(jinja2_vals, n.target.name):
                # selectors!

                # this block runs if we see the key for the
                # first time
                if n.target.name in jinja2_vals:
                    # we need to adjust the previous key
                    # first get the data right after the key we have
                    jinja2_data = (
                        all_nodes[jinja2_vals[n.target.name][1]+1]
                        .nodes[0]
                        .data
                    )

                    # now pull out the selector and reset the key
                    selector_re = SELECTOR_RE.match(jinja2_data)
                    if selector_re is not None:
                        selector = selector_re.group(1)
                        new_key = n.target.name + CONDA_SELECTOR + selector
                        jinja2_vals[new_key] = jinja2_vals[n.target.name]
                        del jinja2_vals[n.target.name]
                    else:
                        assert False, jinja2_data

                # now insert this key - selector is the next thing
                jinja2_data = all_nodes[i+1].nodes[0].data
                selector_re = SELECTOR_RE.match(jinja2_data)
                if selector_re is not None:
                    selector = selector_re.group(1)
                    new_key = n.target.name + CONDA_SELECTOR + selector
                    jinja2_vals[new_key] = (n.node.value, i)
                else:
                    assert False, jinja2_data
            else:
                jinja2_vals[n.target.name] = (n.node.value, i)

    # we don't need the indexes into the jinja2 node list anymore
    for key, val in jinja2_vals.items():
        jinja2_vals[key] = jinja2_vals[key][0]

    return jinja2_vals


def _munge_line(line: str) -> str:
    """turn lines like

        key: val  # [sel]

    to

        key__###conda-selector###__sel: val
    """
    m = SPC_KEY_VAL_SELECTOR_RE.match(line)
    if m:
        spc, key, val, selector = m.group(1, 2, 3, 4)
        new_key = key + CONDA_SELECTOR + selector
        return spc + new_key + ':' + val + '\n'
    else:
        return line


def _unmunge_line(line: str) -> str:
    """turn lines like

        key__###conda-selector###__sel: val

    to

        key: val  # [sel]

    This one does the opposite of _munge_line above.
    """
    m = MUNGED_LINE_RE.match(line)
    if m:
        spc, key, selector, val = m.group(1, 2, 3, 4)
        return spc + key + ': ' + val.strip() + '  # [' + selector + ']\n'
    else:
        return line


def _demunge_jinja2_vars(meta: Union[dict, list]) -> Union[dict, list]:
    """recursively iterate through dictionary / list and replace any instance
    in any string of `<{` with '{{'
    """
    if isinstance(meta, collections.abc.MutableMapping):
        for key, val in meta.items():
            meta[key] = _demunge_jinja2_vars(val)
        return meta
    elif isinstance(meta, collections.abc.MutableSequence):
        for i in range(len(meta)):
            meta[i] = _demunge_jinja2_vars(meta[i])
        return meta
    elif isinstance(meta, str):
        return meta.replace('<{', '{{')
    else:
        return meta


def _remunge_jinja2_vars(meta: Union[dict, list]) -> Union[dict, list]:
    """recursively iterate through dictionary / list and replace any instance
    in any string of `{{` with '<{'
    """
    if isinstance(meta, collections.abc.MutableMapping):
        for key, val in meta.items():
            meta[key] = _remunge_jinja2_vars(val)
        return meta
    elif isinstance(meta, collections.abc.MutableSequence):
        for i in range(len(meta)):
            meta[i] = _remunge_jinja2_vars(meta[i])
        return meta
    elif isinstance(meta, str):
        return meta.replace('{{', '<{')
    else:
        return meta


def _replace_jinja2_vars(lines: List[str], jinja2_vars: dict) -> List[str]:
    """Find all instances of jinja2 vairable assignment via `set` in a recipe
    and replace the values with those in `jinja2_vars`. Any extra key-value
    pairs in `jinja2_vars` will be added as new statements at the top.
    """
    # these regex find jinja2 set statements without and with selectors
    jinja2_re = re.compile(r'^(\s*){%\s*set\s*(.*)=\s*(.*)%}(.*)')
    jinja2_re_selector = re.compile(r'^(\s*){%\s*set\s*(.*)=\s*(.*)%}\s*#\s*\[(.*)\]')

    all_jinja2_keys = set(list(jinja2_vars.keys()))
    used_jinja2_keys = set()

    # first replace everything we can
    # we track which kets have been used so we can add any unused keys ar the
    # end
    new_lines = []
    for line in lines:
        _re_sel = jinja2_re_selector.match(line)
        _re = jinja2_re.match(line)

        if _re_sel:
            # if the line has a selector in it, then we need to pull
            # out the right key with the selector from jinja2_vars
            spc, var, val, sel = _re_sel.group(1, 2, 3, 4)
            key = var.strip() + CONDA_SELECTOR + sel
            if key in jinja2_vars:
                _new_line = (
                    spc
                    + '{% set '
                    + var.strip()
                    + ' = '
                    + json.dumps(jinja2_vars[key])
                    + ' %}  # ['
                    + sel
                    + ']\n'
                )
                used_jinja2_keys.add(key)
            else:
                _new_line = line
        elif _re:
            # no selector
            spc, var, val, end = _re.group(1, 2, 3, 4)
            if var.strip() in jinja2_vars:
                _new_line = (
                    spc
                    + '{% set '
                    + var.strip()
                    + ' = '
                    + json.dumps(jinja2_vars[var.strip()])
                    + ' %}'
                    + end
                )
                used_jinja2_keys.add(var.strip())
            else:
                _new_line = line
        else:
            _new_line = line

        if _new_line is not None:
            if _new_line[-1] != '\n':
                _new_line = _new_line + '\n'

            new_lines.append(_new_line)

    # any unused keys, possibly with selectors, get added here
    if all_jinja2_keys != used_jinja2_keys:
        extra_lines = []
        extra_jinja2_keys = all_jinja2_keys - used_jinja2_keys
        for key in sorted(list(extra_jinja2_keys)):
            if CONDA_SELECTOR in key:
                _key, selector = key.split(CONDA_SELECTOR)
                extra_lines.append(
                    '{% set '
                    + _key
                    + ' = '
                    + json.dumps(jinja2_vars[key])
                    + ' %}'
                    + '  # ['
                    + selector
                    + ']\n'
                )
            else:
                extra_lines.append(
                    '{% set '
                    + key
                    + ' = '
                    + json.dumps(jinja2_vars[key])
                    + ' %}'
                    + '\n'
                )

        new_lines = extra_lines + new_lines

    return new_lines


class CondaMetaYAML(object):
    """Crude parsing of conda recipes.

    NOTE: This parser does not handle any jinja2 constructs besides
    referencing variables (e.g., `{{ var }}`) or setting variables
    (e.g., `{% set var = val %}`).

    Parameters
    ----------
    meta_yaml : str
        The recipe as a string.

    Attributes
    ----------
    meta : dict
        The parsed recipe. Note that selectors for dictionary entries
        get embedded into the dictionary key via the transformation

            key: val  # [sel]

        to

            key__###conda-selector###__sel: val

        If you use the `dump` method, this transformation is undone.
    jinja2_vars : dict
        A dictionary mapping the names of any set jinja2 variables to their
        values. Any entries added to this dictionary are inserted at the
        top of the recipe. You can use the mangling of the keys for selectors
        to add selectors to values as well. Finally, any changes to existing
        values are put into the recipe as well.

    Methods
    -------
    dump(fp):
        Dump the recipe to a file-like object. Note that the mangling of dictionary
        keys for selectors is undone at this step. Dumping the raw `meta` attribute
        will not produce the correct recipe.
    """
    def __init__(self, meta_yaml: str):
        # get any variables set in the file by jinja2
        self.jinja2_vars = _parse_jinja2_variables(meta_yaml)

        # munge any duplicate keys
        in_data = io.StringIO(meta_yaml)
        in_data.seek(0)
        lines = []
        for line in in_data.readlines():
            lines.append(_munge_line(line))

        # parse with yaml
        self.meta = YAML_JINJA2.load(''.join(lines))

        # undo munging of jinja2 variables '<{ var }}' -> '{{ var }}'
        self.meta = _demunge_jinja2_vars(self.meta)

    def dump(self, fp: Any):
        """Dump the recipe to a file-like object.

        Parameters
        ----------
        fp : file-like object
            A file-like object with a `write` method that accepts strings.
        """
        # redo jinja2 changes
        self.meta = _remunge_jinja2_vars(self.meta)

        try:
            # first dump to yaml
            s = io.StringIO()
            YAML_JINJA2.dump(self.meta, s)
            s.seek(0)

            # now unmunge
            lines = []
            for line in s.readlines():
                lines.append(_unmunge_line(line))

            # put in new jinja2 vars
            lines = _replace_jinja2_vars(lines, self.jinja2_vars)

            # now write to final loc
            for line in lines:
                fp.write(line)
        finally:
            # always put things back!
            self.meta = _demunge_jinja2_vars(self.meta)
