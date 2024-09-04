from jinja2 import DebugUndefined


class _MissingUndefined(DebugUndefined):
    def __str__(self) -> str:
        """
        By default, `DebugUndefined` return values in the form `{{ value }}`.
        `rattler-build` has a different syntax, so we need to override this method,
        and return the value in the form `${{ value }}`.
        """
        return f"${super().__str__()}"
