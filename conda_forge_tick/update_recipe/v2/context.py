import jinja2


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
