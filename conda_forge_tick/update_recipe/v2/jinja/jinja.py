from __future__ import annotations

from typing import TypedDict

import jinja2
from jinja2.sandbox import SandboxedEnvironment

from conda_forge_tick.update_recipe.v2.jinja.filters import (
    _bool,
    _split,
    _version_to_build_string,
)
from conda_forge_tick.update_recipe.v2.jinja.objects import (
    _stub_compatible_pin,
    _stub_is_linux,
    _stub_is_unix,
    _stub_is_win,
    _stub_match,
    _stub_subpackage_pin,
    _StubEnv,
)
from conda_forge_tick.update_recipe.v2.jinja.utils import _MissingUndefined

# from conda_forge_tick.update_recipe.v2.loader import load_yaml


class RecipeWithContext(TypedDict, total=False):
    context: dict[str, str]


def jinja_env() -> SandboxedEnvironment:
    """
    Create a `rattler-build` specific Jinja2 environment with modified syntax.
    Target platform, build platform, and mpi are set to linux-64 by default.
    """
    env = SandboxedEnvironment(
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


def load_recipe_context(
    context: dict[str, str], jinja_env: jinja2.Environment
) -> dict[str, str]:
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
