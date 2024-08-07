from __future__ import annotations

from typing import Any, TypedDict

import jinja2
import yaml

from rattler_build_conda_compat.jinja.filters import _bool, _split, _version_to_build_string
from rattler_build_conda_compat.jinja.objects import (
    _stub_compatible_pin,
    _stub_is_linux,
    _stub_is_unix,
    _stub_is_win,
    _stub_match,
    _stub_subpackage_pin,
    _StubEnv,
)
from rattler_build_conda_compat.jinja.utils import _MissingUndefined
from rattler_build_conda_compat.loader import load_yaml


class RecipeWithContext(TypedDict, total=False):
    context: dict[str, str]


def jinja_env() -> jinja2.Environment:
    """
    Create a `rattler-build` specific Jinja2 environment with modified syntax.
    Target platform, build platform, and mpi are set to linux-64 by default.
    """
    env = jinja2.sandbox.SandboxedEnvironment(
        variable_start_string="${{",
        variable_end_string="}}",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=jinja2.select_autoescape(default_for_string=False),
        undefined=_MissingUndefined,
    )

    env_obj = _StubEnv()

    # inject rattler-build recipe functions in jinja environment
    env.globals.update(
        {
            "compiler": lambda x: x + "_compiler_stub",
            "stdlib": lambda x: x + "_stdlib_stub",
            "pin_subpackage": _stub_subpackage_pin,
            "pin_compatible": _stub_compatible_pin,
            "cdt": lambda *args, **kwargs: "cdt_stub",  # noqa: ARG005
            "env": env_obj,
            "match": _stub_match,
            "is_unix": _stub_is_unix,
            "is_win": _stub_is_win,
            "is_linux": _stub_is_linux,
            "unix": True,
            "linux": True,
            "target_platform": "linux-64",
            "build_platform": "linux-64",
            "mpi": "mpi",
        }
    )

    # inject rattler-build recipe filters in jinja environment
    env.filters.update(
        {
            "version_to_buildstring": _version_to_build_string,
            "split": _split,
            "bool": _bool,
        }
    )
    return env


def load_recipe_context(context: dict[str, str], jinja_env: jinja2.Environment) -> dict[str, str]:
    """
    Load all string values from the context dictionary as Jinja2 templates.
    Use linux-64 as default target_platform, build_platform, and mpi.
    """
    # Process each key-value pair in the dictionary
    for key, value in context.items():
        # If the value is a string, render it as a template
        if isinstance(value, str):
            template = jinja_env.from_string(value)
            rendered_value = template.render(context)
            context[key] = rendered_value

    return context


def render_recipe_with_context(recipe_content: RecipeWithContext) -> dict[str, Any]:
    """
    Render the recipe using known values from context section.
    Unknown values are not evaluated and are kept as it is.
    Target platform, build platform, and mpi are set to linux-64 by default.

    Examples:
    ---
    ```python
    >>> from pathlib import Path
    >>> from rattler_build_conda_compat.loader import load_yaml
    >>> recipe_content = load_yaml((Path().resolve() / "tests" / "data" / "eval_recipe_using_context.yaml").read_text())
    >>> evaluated_context = render_recipe_with_context(recipe_content)
    >>> assert "my_value-${{ not_present_value }}" == evaluated_context["build"]["string"]
    >>>
    ```
    """
    env = jinja_env()
    context = recipe_content.get("context", {})
    # render out the context section and retrieve dictionary
    context_variables = load_recipe_context(context, env)

    # render the rest of the document with the values from the context
    # and keep undefined expressions _as is_.
    template = env.from_string(yaml.dump(recipe_content))
    rendered_content = template.render(context_variables)
    return load_yaml(rendered_content)
