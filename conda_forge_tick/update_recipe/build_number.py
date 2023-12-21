import re

DEFAULT_BUILD_PATTERNS = (
    (re.compile(r"(\s*?)number:\s*([0-9]+)"), "number: {}"),
    (
        re.compile(r'(\s*?){%\s*set build_number\s*=\s*"?([0-9]+)"?\s*%}'),
        "{{% set build_number = {} %}}",
    ),
    (
        re.compile(r'(\s*?){%\s*set build\s*=\s*"?([0-9]+)"?\s*%}'),
        "{{% set build = {} %}}",
    ),
)


def update_build_number(raw_meta_yaml, new_build_number, build_patterns=None):
    """Update the build number for a recipe.

    Parameters
    ----------
    raw_meta_yaml : str
        The meta.yaml as a string.
    new_build_number : int or callable
        The new build number to set in the recipe. If callable, should be a function
        that accepts a the old build number and returns the new one. Otherwise, should
        be the new build number.
    build_patterns : tuple of 2-tuples, optional
        A tuple of 2-tuples with a regex to search for the old build number
        and a string to interpolate when setting the new one. See
        `conda_forge_tick.update_recipe.DEFAULT_BUILD_PATTERNS` for examples.

    Returns
    -------
    updated_meta_yaml : str
        The updated meta.yaml with the build number updated.
    """
    if build_patterns is None:
        build_patterns = DEFAULT_BUILD_PATTERNS

    for p, n in build_patterns:
        lines = raw_meta_yaml.splitlines()
        for i, line in enumerate(lines):
            m = p.match(line)
            if m is not None:
                old_build_number = int(m.group(2))
                if callable(new_build_number):
                    _new_build_number = new_build_number(old_build_number)
                else:
                    _new_build_number = new_build_number
                lines[i] = m.group(1) + n.format(_new_build_number)
        raw_meta_yaml = "\n".join(lines) + "\n"

    return raw_meta_yaml
